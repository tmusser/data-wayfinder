from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Confidence(str, Enum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TableRef(BaseModel):
    name: str
    urn: str | None = None
    platform: str | None = None


class Grain(BaseModel):
    description: str | None = None
    keys: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.UNKNOWN
    evidence: list[str] = Field(default_factory=list)


class FieldProfile(BaseModel):
    sampled_rows: int = 0
    null_count: int | None = None
    null_rate: float | None = None
    distinct_count: int | None = None
    distinct_rate: float | None = None
    min: Any | None = None
    max: Any | None = None
    mean: float | None = None
    examples: list[Any] = Field(default_factory=list)
    top_values: list[dict[str, Any]] = Field(default_factory=list)


class FieldCatalogContext(BaseModel):
    description: str | None = None
    glossary_terms: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class FieldAudit(BaseModel):
    name: str
    data_type: str | None = None
    nullable: bool | None = None
    inferred_role: Literal[
        "identifier", "dimension", "measure", "timestamp", "boolean", "unknown"
    ] = "unknown"
    profile: FieldProfile = Field(default_factory=FieldProfile)
    metadata: FieldCatalogContext = Field(default_factory=FieldCatalogContext)


class RelationshipEvidence(BaseModel):
    source: Literal[
        "query_sql",
        "datahub_lineage",
        "datahub_query_history",
        "declared_constraint",
        "live_profile",
        "user_assertion",
    ]
    kind: str
    detail: str | None = None
    weight: float | None = Field(default=None, ge=0, le=1)


class RelationshipAudit(BaseModel):
    left_table: str
    left_field: str | None = None
    right_table: str
    right_field: str | None = None
    join_type: str | None = None
    cardinality: Literal[
        "one_to_one",
        "one_to_many",
        "many_to_one",
        "many_to_many",
        "unknown",
    ] = "unknown"
    match_rate_left: float | None = None
    match_rate_right: float | None = None
    row_expansion: float | None = None
    confidence: Confidence = Confidence.UNKNOWN
    evidence: list[RelationshipEvidence] = Field(default_factory=list)


class CatalogContext(BaseModel):
    description: str | None = None
    owner: str | None = None
    owners: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    glossary_terms: list[str] = Field(default_factory=list)
    domain: str | None = None
    quality_signals: list[str] = Field(default_factory=list)
    upstream: list[str] = Field(default_factory=list)
    downstream: list[str] = Field(default_factory=list)
    observed_queries: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class TableProfile(BaseModel):
    rows: int | None = None
    sampled_rows: int = 0
    columns: int | None = None


class TableAudit(BaseModel):
    table: TableRef
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    identity: Grain = Field(default_factory=Grain)
    profile: TableProfile = Field(default_factory=TableProfile)
    freshness_field: str | None = None
    freshness_max: Any | None = None
    fields: dict[str, FieldAudit] = Field(default_factory=dict)
    metadata: CatalogContext = Field(default_factory=CatalogContext)
    relationships: list[RelationshipAudit] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class QueryTable(BaseModel):
    name: str
    alias: str | None = None


class QueryMap(BaseModel):
    dialect: str | None = None
    tables: list[QueryTable] = Field(default_factory=list)
    relationships: list[RelationshipAudit] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
