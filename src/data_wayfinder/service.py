from __future__ import annotations

from data_wayfinder.datasources.base import DataSource, ProfileBudget
from data_wayfinder.models import TableAudit
from data_wayfinder.profiling import profile_table
from data_wayfinder.providers.base import MetadataProvider


def inspect_table(
    source: DataSource,
    table: str,
    *,
    budget: ProfileBudget | None = None,
    metadata: MetadataProvider | None = None,
    table_urn: str | None = None,
) -> TableAudit:
    audit = profile_table(source, table, budget)

    if metadata and table_urn:
        audit.table.urn = table_urn
        audit.metadata = metadata.table_context(table_urn)
        for field_name, field_audit in audit.fields.items():
            field_audit.metadata = metadata.field_context(table_urn, field_name)
    elif metadata and not table_urn:
        audit.warnings.append(
            "Metadata provider supplied without a table URN; catalog enrichment skipped."
        )

    return audit


def inspect_relationship(
    source,
    left_table: str,
    left_field: str,
    right_table: str,
    right_field: str,
    *,
    join_type: str = "left",
):
    profiler = getattr(source, "profile_relationship", None)
    if profiler is None:
        raise NotImplementedError(
            "This data source does not implement relationship profiling."
        )
    return profiler(
        left_table,
        left_field,
        right_table,
        right_field,
        join_type=join_type,
    )
