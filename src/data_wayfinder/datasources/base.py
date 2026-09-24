from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class ColumnSpec(BaseModel):
    name: str
    data_type: str | None = None
    nullable: bool | None = None


class ProfileBudget(BaseModel):
    sample_rows: int = Field(default=5000, ge=1, le=100_000)
    max_fields: int = Field(default=100, ge=1, le=500)
    max_examples: int = Field(default=5, ge=0, le=20)
    top_values: int = Field(default=8, ge=0, le=50)


class DataSource(Protocol):
    def schema(self, table: str) -> list[ColumnSpec]: ...

    def sample(
        self,
        table: str,
        fields: list[str],
        limit: int,
    ) -> list[dict[str, Any]]: ...

    def row_count(self, table: str) -> int | None: ...
