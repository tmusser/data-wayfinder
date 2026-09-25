# Athena adapter

Athena is the first production-oriented data-plane adapter for data-wayfinder.

The adapter is deliberately conservative:

- schema inspection uses Athena's metadata API and does not execute SQL;
- data inspection uses bounded SELECT ... LIMIT queries;
- Athena result strings are converted back to numeric and boolean Python values before profiling;
- exact COUNT(*) is not run automatically;
- query execution statistics are retained on the adapter and surfaced as audit warnings;
- an optional client-side scan threshold can cancel a running query after Athena reports scanned bytes;
- hard scan limits should be enforced in the Athena workgroup, not trusted to client polling.

## Install

```bash
python -m pip install -e ".[athena]"
```

Authentication follows the normal boto3 credential chain. Prefer an existing AWS
profile, SSO session, workload role, or other short-lived credential mechanism.
Do not put access keys in Wayfinder configuration.

## CLI

```bash
data-wayfinder inspect-athena \
  --database analytics \
  --table customers \
  --workgroup wayfinder-readonly \
  --region us-east-1 \
  --sample-rows 5000
```

If the workgroup does not define an Athena query-results location, pass one:

```bash
  --output-location s3://my-athena-query-results/wayfinder/
```

For repeated inspection where slightly stale samples are acceptable:

```bash
  --result-reuse-minutes 30
```

For a best-effort client cancellation threshold:

```bash
  --client-scan-limit-mb 512
```

That client threshold is not a hard billing boundary. Athena can scan data
between polling calls. Use workgroup-enforced controls for a real server-side
budget.

## Table names

All of these are accepted:

```text
customers
analytics.customers
AwsDataCatalog.analytics.customers
```

The configured catalog and database fill omitted components.

## Intentionally omitted

### Automatic exact row count

The Athena adapter returns `null` for `TableAudit.profile.rows` rather than
issuing `COUNT(*)`. A full-table count can be expensive and violates
Wayfinder's "bound expensive work" principle.

### Relationship probes

The SQLite adapter currently performs exact relationship diagnostics. Athena
does not yet do this because naively porting those queries would turn join
inspection into large scans. A future Athena relationship probe should have a
clear sampling/partition strategy and report its scan cost explicitly.

## IAM and query results

The principal needs access to the Athena workgroup/catalog plus the permissions
required to start and inspect queries. Fetching query results also depends on
access to the configured S3 query-results location.

If a workgroup enforces its own query result configuration, that configuration
can override the client-side output location.

## Programmatic use

```python
from data_wayfinder.datasources import AthenaConfig, AthenaDataSource
from data_wayfinder.service import inspect_table

source = AthenaDataSource(
    AthenaConfig(
        database="analytics",
        workgroup="wayfinder-readonly",
        region_name="us-east-1",
    )
)

audit = inspect_table(source, "customers")
print(audit.model_dump_json(indent=2))
```

After a sample query, `source.last_query_stats` contains the Athena query ID,
bytes scanned, execution times, result-reuse flag, and result output location.
