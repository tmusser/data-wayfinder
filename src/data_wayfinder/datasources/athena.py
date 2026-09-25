from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from pydantic import BaseModel, Field

from .base import ColumnSpec


class AthenaError(RuntimeError):
    """Base error for Athena datasource operations."""


class AthenaQueryError(AthenaError):
    """Raised when Athena reports a failed or cancelled query."""


class AthenaQueryTimeout(AthenaError):
    """Raised when a query exceeds the configured client timeout."""


class AthenaScanLimitExceeded(AthenaError):
    """Raised after best-effort cancellation when scan bytes exceed the client limit."""


class AthenaConfig(BaseModel):
    database: str
    catalog: str = "AwsDataCatalog"
    workgroup: str | None = "primary"
    output_location: str | None = None
    region_name: str | None = None
    profile_name: str | None = None
    poll_interval_seconds: float = Field(default=0.5, ge=0)
    timeout_seconds: float = Field(default=90.0, gt=0)
    client_scan_limit_bytes: int | None = Field(default=None, gt=0)
    result_reuse_minutes: int = Field(default=0, ge=0, le=10080)


class AthenaQueryStats(BaseModel):
    query_execution_id: str
    data_scanned_bytes: int | None = None
    total_execution_time_ms: int | None = None
    engine_execution_time_ms: int | None = None
    result_reused: bool | None = None
    output_location: str | None = None


_INTEGER_TYPES = {"tinyint", "smallint", "integer", "int", "bigint"}
_FLOAT_TYPES = {"real", "float", "double"}


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _split_table_name(table: str, config: AthenaConfig) -> tuple[str, str, str]:
    parts = [part.strip() for part in table.split(".") if part.strip()]
    if len(parts) == 1:
        return config.catalog, config.database, parts[0]
    if len(parts) == 2:
        return config.catalog, parts[0], parts[1]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    raise ValueError(
        "Athena table names must be table, database.table, or catalog.database.table."
    )


def _coerce(value: str | None, athena_type: str) -> Any:
    if value is None:
        return None
    normalized = athena_type.lower().strip()
    try:
        if normalized in _INTEGER_TYPES:
            return int(value)
        if normalized in _FLOAT_TYPES:
            return float(value)
        if normalized.startswith("decimal"):
            return Decimal(value)
        if normalized == "boolean":
            return value.lower() == "true"
    except (ValueError, InvalidOperation):
        return value
    return value


class AthenaDataSource:
    """Read-only Athena datasource focused on bounded inspection.

    Schema reads use Athena's metadata API and do not execute SQL. Data samples
    execute SELECT ... LIMIT queries. Exact row counts are intentionally not
    issued because COUNT(*) can scan an entire table.

    client_scan_limit_bytes is a best-effort client-side cancellation guard,
    not a hard cost ceiling. Use an Athena workgroup with enforced scan limits
    for a true server-side guardrail.
    """

    def __init__(
        self,
        config: AthenaConfig,
        *,
        client: Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ):
        self.config = config
        self._sleep = sleep_fn
        self._monotonic = monotonic_fn
        self.last_query_stats: AthenaQueryStats | None = None

        if client is not None:
            self.client = client
            return

        try:
            import boto3
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                'Athena support requires the optional dependency: '
                'pip install "data-wayfinder[athena]"'
            ) from exc

        session = boto3.Session(
            profile_name=config.profile_name,
            region_name=config.region_name,
        )
        self.client = session.client("athena")

    def schema(self, table: str) -> list[ColumnSpec]:
        catalog, database, table_name = _split_table_name(table, self.config)
        request: dict[str, Any] = {
            "CatalogName": catalog,
            "DatabaseName": database,
            "TableName": table_name,
        }
        if self.config.workgroup:
            request["WorkGroup"] = self.config.workgroup

        response = self.client.get_table_metadata(**request)
        metadata = response.get("TableMetadata", {})
        columns = list(metadata.get("Columns", [])) + list(
            metadata.get("PartitionKeys", [])
        )

        result: list[ColumnSpec] = []
        seen: set[str] = set()
        for column in columns:
            name = column.get("Name")
            if not name or name in seen:
                continue
            seen.add(name)
            result.append(
                ColumnSpec(
                    name=name,
                    data_type=column.get("Type"),
                    nullable=None,
                )
            )
        return result

    def sample(
        self,
        table: str,
        fields: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0 or not fields:
            return []

        catalog, database, table_name = _split_table_name(table, self.config)
        qualified = ".".join(
            _quote_identifier(part) for part in (catalog, database, table_name)
        )
        selected = ", ".join(_quote_identifier(field) for field in fields)
        query = f"SELECT {selected} FROM {qualified} LIMIT {int(limit)}"
        return self._execute_select(query, max_rows=limit)

    def row_count(self, table: str) -> int | None:
        # Deliberately omitted: COUNT(*) on Athena can force a full scan.
        return None

    def audit_warnings(self) -> list[str]:
        warnings = [
            "Athena exact row count was not queried because COUNT(*) may scan "
            "the full table."
        ]
        if self.last_query_stats and self.last_query_stats.data_scanned_bytes is not None:
            scanned = self.last_query_stats.data_scanned_bytes
            reused = self.last_query_stats.result_reused is True
            suffix = " (reused cached result)" if reused else ""
            warnings.append(f"Athena sample query scanned {scanned} bytes{suffix}.")
        if self.config.client_scan_limit_bytes is not None:
            warnings.append(
                "Athena client scan limit is best-effort cancellation; enforce "
                "hard byte limits in the Athena workgroup."
            )
        return warnings

    def _execute_select(
        self,
        query: str,
        *,
        max_rows: int,
    ) -> list[dict[str, Any]]:
        request: dict[str, Any] = {
            "QueryString": query,
            "QueryExecutionContext": {
                "Database": self.config.database,
                "Catalog": self.config.catalog,
            },
        }
        if self.config.workgroup:
            request["WorkGroup"] = self.config.workgroup
        if self.config.output_location:
            request["ResultConfiguration"] = {
                "OutputLocation": self.config.output_location
            }
        if self.config.result_reuse_minutes > 0:
            request["ResultReuseConfiguration"] = {
                "ResultReuseByAgeConfiguration": {
                    "Enabled": True,
                    "MaxAgeInMinutes": self.config.result_reuse_minutes,
                }
            }

        started = self.client.start_query_execution(**request)
        query_id = started["QueryExecutionId"]
        deadline = self._monotonic() + self.config.timeout_seconds

        while True:
            execution = self.client.get_query_execution(
                QueryExecutionId=query_id
            )["QueryExecution"]
            status = execution.get("Status", {})
            state = status.get("State")
            statistics = execution.get("Statistics", {})
            scanned = statistics.get("DataScannedInBytes")

            if (
                self.config.client_scan_limit_bytes is not None
                and scanned is not None
                and scanned > self.config.client_scan_limit_bytes
                and state not in {"SUCCEEDED", "FAILED", "CANCELLED"}
            ):
                self.client.stop_query_execution(QueryExecutionId=query_id)
                raise AthenaScanLimitExceeded(
                    f"Athena query {query_id} observed {scanned} scanned bytes, "
                    f"above client limit {self.config.client_scan_limit_bytes}."
                )

            if state == "SUCCEEDED":
                break
            if state in {"FAILED", "CANCELLED"}:
                reason = status.get("StateChangeReason") or "no reason returned"
                raise AthenaQueryError(
                    f"Athena query {query_id} {state}: {reason}"
                )
            if self._monotonic() >= deadline:
                self.client.stop_query_execution(QueryExecutionId=query_id)
                raise AthenaQueryTimeout(
                    f"Athena query {query_id} exceeded "
                    f"{self.config.timeout_seconds}s timeout."
                )
            self._sleep(self.config.poll_interval_seconds)

        self.last_query_stats = self._stats_from_execution(query_id, execution)
        return self._read_results(query_id, max_rows=max_rows)

    def _stats_from_execution(
        self,
        query_id: str,
        execution: dict[str, Any],
    ) -> AthenaQueryStats:
        statistics = execution.get("Statistics", {})
        result_config = execution.get("ResultConfiguration", {})
        reuse = statistics.get("ResultReuseInformation", {}).get(
            "ReusedPreviousResult"
        )
        return AthenaQueryStats(
            query_execution_id=query_id,
            data_scanned_bytes=statistics.get("DataScannedInBytes"),
            total_execution_time_ms=statistics.get("TotalExecutionTimeInMillis"),
            engine_execution_time_ms=statistics.get(
                "EngineExecutionTimeInMillis"
            ),
            result_reused=reuse,
            output_location=result_config.get("OutputLocation"),
        )

    def _read_results(
        self,
        query_id: str,
        *,
        max_rows: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        next_token: str | None = None
        metadata: list[dict[str, Any]] | None = None
        first_data_row = True

        while len(rows) < max_rows:
            request: dict[str, Any] = {
                "QueryExecutionId": query_id,
                "MaxResults": min(1000, max_rows + 1),
            }
            if next_token:
                request["NextToken"] = next_token

            page = self.client.get_query_results(**request)
            result_set = page.get("ResultSet", {})
            if metadata is None:
                metadata = result_set.get("ResultSetMetadata", {}).get(
                    "ColumnInfo", []
                )

            column_names = [column.get("Name", "") for column in metadata]
            column_types = [
                column.get("Type", "varchar") for column in metadata
            ]

            for raw_row in result_set.get("Rows", []):
                data = raw_row.get("Data", [])
                raw_values = [
                    item.get("VarCharValue")
                    if isinstance(item, dict)
                    else None
                    for item in data
                ]
                if first_data_row:
                    first_data_row = False
                    if raw_values == column_names:
                        continue

                values = raw_values + [None] * max(
                    0, len(column_names) - len(raw_values)
                )
                rows.append(
                    {
                        name: _coerce(values[index], column_types[index])
                        for index, name in enumerate(column_names)
                    }
                )
                if len(rows) >= max_rows:
                    break

            next_token = page.get("NextToken")
            if not next_token:
                break

        return rows
