from data_wayfinder.datasources.athena import (
    AthenaConfig,
    AthenaDataSource,
    AthenaScanLimitExceeded,
)
from data_wayfinder.datasources.base import ProfileBudget
from data_wayfinder.profiling import profile_table


class FakeAthenaClient:
    def __init__(self):
        self.started = []
        self.stopped = []
        self.result_calls = []

    def get_table_metadata(self, **kwargs):
        self.metadata_request = kwargs
        return {
            "TableMetadata": {
                "Columns": [
                    {"Name": "customer_id", "Type": "bigint"},
                    {"Name": "revenue", "Type": "double"},
                ],
                "PartitionKeys": [
                    {"Name": "event_date", "Type": "date"},
                ],
            }
        }

    def start_query_execution(self, **kwargs):
        self.started.append(kwargs)
        return {"QueryExecutionId": "q-123"}

    def get_query_execution(self, **kwargs):
        return {
            "QueryExecution": {
                "Status": {"State": "SUCCEEDED"},
                "Statistics": {
                    "DataScannedInBytes": 4096,
                    "TotalExecutionTimeInMillis": 80,
                    "EngineExecutionTimeInMillis": 50,
                    "ResultReuseInformation": {
                        "ReusedPreviousResult": False
                    },
                },
                "ResultConfiguration": {
                    "OutputLocation": "s3://query-results/q-123.csv"
                },
            }
        }

    def get_query_results(self, **kwargs):
        self.result_calls.append(kwargs)
        return {
            "ResultSet": {
                "ResultSetMetadata": {
                    "ColumnInfo": [
                        {"Name": "customer_id", "Type": "bigint"},
                        {"Name": "revenue", "Type": "double"},
                    ]
                },
                "Rows": [
                    {
                        "Data": [
                            {"VarCharValue": "customer_id"},
                            {"VarCharValue": "revenue"},
                        ]
                    },
                    {
                        "Data": [
                            {"VarCharValue": "1"},
                            {"VarCharValue": "12.5"},
                        ]
                    },
                    {
                        "Data": [
                            {"VarCharValue": "2"},
                            {},
                        ]
                    },
                ],
            }
        }

    def stop_query_execution(self, **kwargs):
        self.stopped.append(kwargs)


def test_schema_uses_metadata_api_without_running_query():
    client = FakeAthenaClient()
    source = AthenaDataSource(
        AthenaConfig(database="analytics", workgroup="wayfinder"),
        client=client,
    )

    schema = source.schema("customers")

    assert [column.name for column in schema] == [
        "customer_id",
        "revenue",
        "event_date",
    ]
    assert client.metadata_request == {
        "CatalogName": "AwsDataCatalog",
        "DatabaseName": "analytics",
        "TableName": "customers",
        "WorkGroup": "wayfinder",
    }
    assert client.started == []


def test_sample_is_bounded_and_exposes_scan_statistics():
    client = FakeAthenaClient()
    source = AthenaDataSource(
        AthenaConfig(
            database="analytics",
            workgroup="wayfinder",
            output_location="s3://query-results/wayfinder/",
            result_reuse_minutes=30,
        ),
        client=client,
    )

    rows = source.sample(
        "customers",
        ["customer_id", "revenue"],
        2,
    )

    assert rows == [
        {"customer_id": 1, "revenue": 12.5},
        {"customer_id": 2, "revenue": None},
    ]
    request = client.started[0]
    assert request["QueryString"] == (
        'SELECT "customer_id", "revenue" '
        'FROM "AwsDataCatalog"."analytics"."customers" LIMIT 2'
    )
    assert request["WorkGroup"] == "wayfinder"
    assert request["ResultConfiguration"] == {
        "OutputLocation": "s3://query-results/wayfinder/"
    }
    assert request["ResultReuseConfiguration"][
        "ResultReuseByAgeConfiguration"
    ] == {
        "Enabled": True,
        "MaxAgeInMinutes": 30,
    }
    assert source.last_query_stats.data_scanned_bytes == 4096


def test_profile_table_keeps_count_unknown_and_reports_scan():
    client = FakeAthenaClient()
    source = AthenaDataSource(
        AthenaConfig(database="analytics"),
        client=client,
    )

    audit = profile_table(
        source,
        "customers",
        ProfileBudget(sample_rows=2),
    )

    assert audit.profile.rows is None
    assert audit.profile.sampled_rows == 2
    assert audit.fields["revenue"].profile.mean == 12.5
    assert any("COUNT(*)" in warning for warning in audit.warnings)
    assert any("4096 bytes" in warning for warning in audit.warnings)


def test_scan_limit_cancels_running_query():
    client = FakeAthenaClient()

    def running_execution(**kwargs):
        return {
            "QueryExecution": {
                "Status": {"State": "RUNNING"},
                "Statistics": {"DataScannedInBytes": 2048},
            }
        }

    client.get_query_execution = running_execution
    source = AthenaDataSource(
        AthenaConfig(
            database="analytics",
            client_scan_limit_bytes=1024,
            poll_interval_seconds=0,
        ),
        client=client,
    )

    try:
        source.sample("customers", ["customer_id"], 1)
        assert False, "expected AthenaScanLimitExceeded"
    except AthenaScanLimitExceeded:
        pass

    assert client.stopped == [{"QueryExecutionId": "q-123"}]
