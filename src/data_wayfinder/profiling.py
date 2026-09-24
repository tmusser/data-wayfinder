from __future__ import annotations

from collections import Counter
from numbers import Number
from typing import Any

from data_wayfinder.datasources.base import DataSource, ProfileBudget
from data_wayfinder.models import FieldAudit, FieldProfile, TableAudit, TableProfile, TableRef


IDENTIFIER_SUFFIXES = ("_id", "_key", "_uuid")
TIMESTAMP_TOKENS = ("date", "time", "_at", "timestamp")


def infer_role(name: str, data_type: str | None, distinct_rate: float | None) -> str:
    lowered = name.lower()
    dtype = (data_type or "").lower()
    if lowered == "id" or lowered.endswith(IDENTIFIER_SUFFIXES):
        return "identifier"
    if any(token in lowered for token in TIMESTAMP_TOKENS) or "date" in dtype or "time" in dtype:
        return "timestamp"
    if "bool" in dtype:
        return "boolean"
    if distinct_rate is not None and distinct_rate >= 0.98:
        return "identifier"
    if any(token in dtype for token in ("int", "real", "float", "double", "decimal", "numeric")):
        return "measure"
    if dtype:
        return "dimension"
    return "unknown"


def _stable_examples(values: list[Any], limit: int) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        marker = repr(value)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def _profile_field(
    name: str,
    data_type: str | None,
    nullable: bool | None,
    rows: list[dict[str, Any]],
    budget: ProfileBudget,
) -> FieldAudit:
    values = [row.get(name) for row in rows]
    non_null = [value for value in values if value is not None]
    sampled = len(values)
    null_count = sampled - len(non_null)
    distinct_markers = {repr(value) for value in non_null}
    distinct_count = len(distinct_markers)

    numeric = [
        float(value)
        for value in non_null
        if isinstance(value, Number) and not isinstance(value, bool)
    ]

    counts = Counter(repr(value) for value in non_null)
    representative = {repr(value): value for value in non_null}
    top_values = [
        {"value": representative[marker], "count": count}
        for marker, count in counts.most_common(budget.top_values)
    ]

    profile = FieldProfile(
        sampled_rows=sampled,
        null_count=null_count,
        null_rate=(null_count / sampled) if sampled else None,
        distinct_count=distinct_count,
        distinct_rate=(distinct_count / len(non_null)) if non_null else None,
        min=min(numeric) if numeric else None,
        max=max(numeric) if numeric else None,
        mean=(sum(numeric) / len(numeric)) if numeric else None,
        examples=_stable_examples(non_null, budget.max_examples),
        top_values=top_values,
    )
    return FieldAudit(
        name=name,
        data_type=data_type,
        nullable=nullable,
        inferred_role=infer_role(name, data_type, profile.distinct_rate),
        profile=profile,
    )


def profile_table(
    source: DataSource,
    table: str,
    budget: ProfileBudget | None = None,
) -> TableAudit:
    budget = budget or ProfileBudget()
    schema = source.schema(table)
    selected = schema[: budget.max_fields]
    rows = source.sample(table, [column.name for column in selected], budget.sample_rows)

    fields = {
        column.name: _profile_field(
            column.name,
            column.data_type,
            column.nullable,
            rows,
            budget,
        )
        for column in selected
    }

    warnings: list[str] = []
    if len(schema) > budget.max_fields:
        warnings.append(
            f"Profile limited to {budget.max_fields} of {len(schema)} fields."
        )
    if len(rows) >= budget.sample_rows:
        warnings.append(
            f"Field statistics are based on at most {budget.sample_rows} sampled rows."
        )

    return TableAudit(
        table=TableRef(name=table),
        profile=TableProfile(
            rows=source.row_count(table),
            sampled_rows=len(rows),
            columns=len(schema),
        ),
        fields=fields,
        warnings=warnings,
    )
