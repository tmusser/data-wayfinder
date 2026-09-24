from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .base import ColumnSpec


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


class SQLiteDataSource:
    """Small working adapter used for local demos and contract tests."""

    def __init__(self, path: str | Path):
        self.path = str(path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def schema(self, table: str) -> list[ColumnSpec]:
        with self._connect() as conn:
            rows = conn.execute(f"PRAGMA table_info({_quote_ident(table)})").fetchall()
        if not rows:
            raise ValueError(f"Table not found: {table}")
        return [
            ColumnSpec(
                name=row["name"],
                data_type=row["type"] or None,
                nullable=not bool(row["notnull"]),
            )
            for row in rows
        ]

    def sample(
        self,
        table: str,
        fields: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        selected = ", ".join(_quote_ident(field) for field in fields)
        sql = f"SELECT {selected} FROM {_quote_ident(table)} LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
        return [dict(row) for row in rows]

    def row_count(self, table: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM {_quote_ident(table)}"
            ).fetchone()
        return int(row["n"])

    def profile_relationship(
        self,
        left_table: str,
        left_field: str,
        right_table: str,
        right_field: str,
        *,
        join_type: str = "left",
    ):
        from data_wayfinder.models import (
            Confidence,
            RelationshipAudit,
            RelationshipEvidence,
        )

        lt = _quote_ident(left_table)
        lf = _quote_ident(left_field)
        rt = _quote_ident(right_table)
        rf = _quote_ident(right_field)

        with self._connect() as conn:
            left = conn.execute(
                f"""
                SELECT
                  COUNT(*) AS rows,
                  COUNT({lf}) AS non_null,
                  COUNT(DISTINCT {lf}) AS distinct_keys
                FROM {lt}
                """
            ).fetchone()
            right = conn.execute(
                f"""
                SELECT
                  COUNT(*) AS rows,
                  COUNT({rf}) AS non_null,
                  COUNT(DISTINCT {rf}) AS distinct_keys
                FROM {rt}
                """
            ).fetchone()
            matched = conn.execute(
                f"""
                SELECT COUNT(DISTINCT l.{lf}) AS matched_keys
                FROM {lt} AS l
                INNER JOIN {rt} AS r
                  ON l.{lf} = r.{rf}
                WHERE l.{lf} IS NOT NULL
                """
            ).fetchone()
            left_join_rows = conn.execute(
                f"""
                SELECT COUNT(*) AS rows
                FROM {lt} AS l
                LEFT JOIN {rt} AS r
                  ON l.{lf} = r.{rf}
                """
            ).fetchone()["rows"]

        left_distinct = int(left["distinct_keys"])
        right_distinct = int(right["distinct_keys"])
        left_non_null = int(left["non_null"])
        right_non_null = int(right["non_null"])
        matched_keys = int(matched["matched_keys"])

        left_unique = left_non_null > 0 and left_distinct == left_non_null
        right_unique = right_non_null > 0 and right_distinct == right_non_null

        if left_unique and right_unique:
            cardinality = "one_to_one"
        elif left_unique and not right_unique:
            cardinality = "one_to_many"
        elif not left_unique and right_unique:
            cardinality = "many_to_one"
        elif left_non_null and right_non_null:
            cardinality = "many_to_many"
        else:
            cardinality = "unknown"

        left_rows = int(left["rows"])
        return RelationshipAudit(
            left_table=left_table,
            left_field=left_field,
            right_table=right_table,
            right_field=right_field,
            join_type=join_type,
            cardinality=cardinality,
            match_rate_left=(matched_keys / left_distinct) if left_distinct else None,
            match_rate_right=(matched_keys / right_distinct) if right_distinct else None,
            row_expansion=(int(left_join_rows) / left_rows) if left_rows else None,
            confidence=Confidence.HIGH,
            evidence=[
                RelationshipEvidence(
                    source="live_profile",
                    kind="sqlite_exact_relationship_probe",
                    detail=(
                        f"left distinct={left_distinct}/{left_non_null}; "
                        f"right distinct={right_distinct}/{right_non_null}; "
                        f"matched distinct keys={matched_keys}; "
                        f"left-join rows={int(left_join_rows)}"
                    ),
                )
            ],
        )
