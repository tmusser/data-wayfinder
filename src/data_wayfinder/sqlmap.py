from __future__ import annotations

import re
from collections import OrderedDict

from data_wayfinder.models import (
    Confidence,
    QueryMap,
    QueryTable,
    RelationshipAudit,
    RelationshipEvidence,
)


def _fallback_map(sql: str, dialect: str | None = None) -> QueryMap:
    """Small fallback for basic SELECT/JOIN SQL when sqlglot is unavailable.

    The installed package uses sqlglot. This fallback keeps the contract usable
    in constrained environments and intentionally handles only simple equality
    joins.
    """
    # Names defined by a WITH clause are CTEs, not warehouse tables -- keep them out of
    # `tables` the same way the sqlglot path below does, even in this degraded fallback.
    cte_name_pattern = re.compile(
        r"\bwith\s+([A-Za-z_]\w*)\s+as\s*\(|,\s*([A-Za-z_]\w*)\s+as\s*\(",
        re.IGNORECASE,
    )
    cte_names = {
        (m.group(1) or m.group(2)).lower() for m in cte_name_pattern.finditer(sql)
    }

    table_pattern = re.compile(
        r"\b(?:from|join)\s+([A-Za-z_][\w.$]*)(?:\s+(?:as\s+)?([A-Za-z_]\w*))?",
        re.IGNORECASE,
    )
    matches = list(table_pattern.finditer(sql))
    alias_lookup: OrderedDict[str, str] = OrderedDict()  # alias/bare name -> canonical name
    tables: OrderedDict[str, QueryTable] = OrderedDict()
    ctes: OrderedDict[str, QueryTable] = OrderedDict()
    reserved = {"on", "where", "left", "right", "inner", "outer", "full", "join"}
    for match in matches:
        name = match.group(1)
        alias = match.group(2)
        if alias and alias.lower() in reserved:
            alias = None

        bucket = ctes if name.lower() in cte_names else tables
        if name not in bucket:
            bucket[name] = QueryTable(name=name, aliases=[])
        if alias and alias not in bucket[name].aliases:
            bucket[name].aliases.append(alias)

        alias_lookup[alias or name.split(".")[-1]] = name
        alias_lookup[name.split(".")[-1]] = name

    relationships: list[RelationshipAudit] = []
    join_pattern = re.compile(
        r"\b(left|right|inner|full|cross)?\s*join\s+"
        r"([A-Za-z_][\w.$]*)(?:\s+(?:as\s+)?([A-Za-z_]\w*))?\s+on\s+"
        r"([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)",
        re.IGNORECASE,
    )
    for match in join_pattern.finditer(sql):
        join_type, _, _, left_alias, left_field, right_alias, right_field = match.groups()
        left_table = alias_lookup.get(left_alias, left_alias)
        right_table = alias_lookup.get(right_alias, right_alias)
        detail = f"{left_alias}.{left_field} = {right_alias}.{right_field}"
        relationships.append(
            RelationshipAudit(
                left_table=left_table,
                left_field=left_field,
                right_table=right_table,
                right_field=right_field,
                join_type=(join_type or "inner").lower(),
                confidence=Confidence.LOW,
                evidence=[
                    RelationshipEvidence(
                        source="query_sql",
                        kind="join_predicate",
                        detail=detail,
                    )
                ],
            )
        )

    warnings = []
    if not tables:
        warnings.append("No tables were resolved from SQL.")
    warnings.append("Parsed with the basic fallback parser; install sqlglot for full parsing.")
    return QueryMap(
        dialect=dialect,
        tables=list(tables.values()),
        ctes=list(ctes.values()),
        relationships=relationships,
        warnings=warnings,
    )


def map_query(sql: str, dialect: str | None = None) -> QueryMap:
    try:
        import sqlglot
        from sqlglot import exp
    except ImportError:
        return _fallback_map(sql, dialect)

    expression = sqlglot.parse_one(sql, read=dialect)

    # Names defined in this query's own WITH clause are query-scoped CTEs, not warehouse
    # tables -- a bare, unqualified reference to one of these names is the CTE, per SQL's
    # own scoping rules (a CTE shadows a same-named real table within its query).
    cte_names = {cte.alias_or_name.lower() for cte in expression.find_all(exp.CTE)}

    tables: OrderedDict[str, QueryTable] = OrderedDict()  # keyed by canonical name
    ctes: OrderedDict[str, QueryTable] = OrderedDict()  # keyed by CTE name
    lookup: dict[str, QueryTable] = {}  # alias or bare name -> the table/CTE it refers to

    for table in expression.find_all(exp.Table):
        parts = [part for part in (table.catalog, table.db, table.name) if part]
        canonical = ".".join(parts)
        alias = table.alias or None
        is_cte = not table.db and not table.catalog and table.name.lower() in cte_names

        bucket = ctes if is_cte else tables
        if canonical not in bucket:
            bucket[canonical] = QueryTable(name=canonical, aliases=[])
        if alias and alias not in bucket[canonical].aliases:
            bucket[canonical].aliases.append(alias)

        lookup[alias or canonical] = bucket[canonical]
        lookup[canonical] = bucket[canonical]

    relationships: list[RelationshipAudit] = []
    for join in expression.find_all(exp.Join):
        on = join.args.get("on")
        if not on:
            continue
        join_type = " ".join(
            str(join.args.get(key) or "")
            for key in ("side", "kind")
        ).strip().lower() or "inner"

        for equality in on.find_all(exp.EQ):
            left = equality.left
            right = equality.right
            if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
                continue
            left_alias = left.table
            right_alias = right.table
            left_table = lookup.get(left_alias)
            right_table = lookup.get(right_alias)
            relationships.append(
                RelationshipAudit(
                    left_table=left_table.name if left_table else left_alias,
                    left_field=left.name,
                    right_table=right_table.name if right_table else right_alias,
                    right_field=right.name,
                    join_type=join_type,
                    confidence=Confidence.MEDIUM,
                    evidence=[
                        RelationshipEvidence(
                            source="query_sql",
                            kind="join_predicate",
                            detail=equality.sql(dialect=dialect),
                        )
                    ],
                )
            )

    return QueryMap(
        dialect=dialect,
        tables=list(tables.values()),
        ctes=list(ctes.values()),
        relationships=relationships,
    )
