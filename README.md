# data-wayfinder

[![CI](https://github.com/tmusser/data-wayfinder/actions/workflows/ci.yml/badge.svg)](https://github.com/tmusser/data-wayfinder/actions/workflows/ci.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Inspect unfamiliar warehouse tables before you trust yourself to analyze them.**

`data-wayfinder` combines bounded live profiling with catalog context, lineage, and relationship evidence so analysts and AI agents can understand the data surface behind a query.

```text
SQL / table
    |
    v
query map -------- DataHub context
    |                   |
    +------ TableAudit -+
              |
      +-------+-------+
      |       |       |
    table   field   relationship
    audit   audit      evidence
```

The graph is navigation. The product is the inspectable analytical context behind every node and edge.

## Why this exists

Data catalogs answer **what the organization knows about a dataset**.

Query editors answer **what SQL will run**.

Profilers answer **what values are present**.

Analysts still have to stitch those surfaces together before they can safely answer basic questions like:

- What is the grain of this table?
- Is this field actually unique?
- What does this join do to row counts?
- How much of the left side matches?
- Is a relationship declared, observed, inferred, or merely present in this SQL?
- What does DataHub say the field means?
- Is there evidence behind the join path I am about to use?

`data-wayfinder` is the inspection layer between **finding data** and **analyzing data**.

## What it is not

It is intentionally not:

- a data catalog;
- a BI dashboard builder;
- an autonomous analyst;
- a semantic-layer replacement;
- a warehouse ingestion framework;
- a guarantee that inferred grain or relationships are correct.

DataHub is a metadata plane. A warehouse adapter is a data plane. Wayfinder keeps those evidence sources distinct rather than collapsing them into one opaque answer.

## Core contract

The durable primitive is a structured `TableAudit`, not a particular UI.

```json
{
  "table": {"name": "analytics.customers"},
  "identity": {
    "description": "one row per customer",
    "keys": ["customer_id"],
    "confidence": "high"
  },
  "profile": {
    "rows": 12382991,
    "sampled_rows": 5000,
    "columns": 41
  },
  "fields": {
    "customer_id": {
      "data_type": "BIGINT",
      "inferred_role": "identifier",
      "profile": {
        "null_rate": 0.0,
        "distinct_rate": 0.99998
      }
    }
  },
  "relationships": []
}
```

CLI tools, notebooks, a web UI, and an MCP server can all consume the same contract.

## Relationship evidence

A relationship is an inspectable object, not just a line in an ERD.

```text
customers.customer_id -> orders.customer_id

Evidence
  SQL text          present
  DataHub lineage   present
  query history     observed
  live profile      left key unique, right key repeated

Observed cardinality     1:N
Left-key match rate      81.2%
Right-key match rate     99.97%
Row expansion            4.71x
Confidence               high
```

Every relationship keeps its underlying evidence records. Confidence is a summary of declared evidence, not truth.

Current evidence sources include:

- `query_sql`
- `datahub_lineage`
- `datahub_query_history`
- `declared_constraint`
- `live_profile`
- `user_assertion`

## Quickstart

Requires Python 3.10+.

```bash
python -m pip install -e ".[dev]"
pytest
```

Create a small SQLite demo warehouse:

```bash
data-wayfinder demo-db examples/demo.db
```

Inspect a table:

```bash
data-wayfinder inspect \
  --sqlite examples/demo.db \
  --table customers \
  --sample-rows 5000
```

Map tables and equality joins from SQL:

```bash
data-wayfinder map examples/customer_orders.sql --dialect sqlite
```

Probe a join:

```bash
data-wayfinder probe-join \
  --sqlite examples/demo.db \
  --left-table customers \
  --left-field customer_id \
  --right-table orders \
  --right-field customer_id
```

The SQLite development adapter returns exact local diagnostics for cardinality, match rates, and left-join row expansion.

Inspect an Athena table:

```bash
python -m pip install -e ".[athena]"

data-wayfinder inspect-athena \
  --database analytics \
  --table customers \
  --workgroup wayfinder-readonly \
  --region us-east-1
```

Athena intentionally leaves exact row count unknown instead of issuing an automatic full-table `COUNT(*)`. See [Athena adapter](docs/athena.md) for credentials, query-result configuration, scan telemetry, result reuse, and cost guardrails.

## CLI

```text
data-wayfinder inspect       bounded SQLite table and field profiling
data-wayfinder inspect-athena bounded Athena table and field profiling
data-wayfinder map           SQL -> tables + relationship evidence
data-wayfinder probe-join    relationship diagnostics
data-wayfinder demo-db       local demo warehouse
```

The CLI deliberately avoids generative conclusions. It exposes evidence and leaves interpretation to the analyst or downstream agent.

## Architecture

```text
                 +----------------------+
                 | analyst SQL / table  |
                 +----------+-----------+
                            |
                            v
                  +-------------------+
                  | query relationship|
                  |       map         |
                  +---------+---------+
                            |
              +-------------+-------------+
              |                           |
              v                           v
     +------------------+        +------------------+
     | metadata plane   |        | data plane       |
     | DataHub MCP      |        | warehouse adapter|
     +--------+---------+        +---------+--------+
              |                            |
              +-------------+--------------+
                            |
                            v
                    +---------------+
                    |  TableAudit   |
                    +-------+-------+
                            |
             +--------------+--------------+
             |              |              |
             v              v              v
            CLI           web UI         agents
```

Current Python core:

```text
src/data_wayfinder/
├── models.py              durable contracts
├── sqlmap.py              SQL -> query map
├── profiling.py           bounded row profiling
├── service.py             orchestration
├── cli.py                 CLI entry point
├── datasources/
│   ├── base.py            data-plane protocol
│   ├── athena.py          AWS Athena adapter
│   └── sqlite.py          working local adapter
└── providers/
    ├── base.py            metadata-plane protocol
    └── datahub_mcp.py     DataHub MCP normalizer
```

## DataHub MCP

Wayfinder treats DataHub as a metadata provider rather than its internal data model.

The adapter currently normalizes calls around:

- `get_entities`
- `list_schema_fields`
- `get_lineage`
- `get_dataset_queries`

The caller owns MCP transport and authentication. Wayfinder accepts a `call_tool` function and preserves the raw returned payload alongside normalized context so provenance is inspectable.

## Profiling budget

Profiling is bounded by default.

`ProfileBudget` controls:

- sampled rows;
- maximum fields;
- maximum example values;
- maximum top values.

The goal is to prevent "inspect this table" from silently becoming an expensive warehouse scan.

The SQLite adapter uses exact relationship probes because it is a local development adapter. Warehouse adapters should expose cost-aware equivalents explicitly.

## v0.1 boundary

The first useful release is intentionally narrow:

1. accept SQL or a table;
2. resolve table and field references;
3. enrich catalog metadata through DataHub MCP;
4. run bounded profiling through a data-plane adapter;
5. inspect relationships and their evidence;
6. export stable JSON contracts.

Not in the initial boundary:

- chatbot-first exploration;
- automatic business conclusions;
- chart generation;
- metric-definition management;
- arbitrary warehouse mutation;
- unbounded profiling;
- hidden "AI confidence" scores.

## Roadmap

### v0.1 — inspect

- [x] `TableAudit`, field, and relationship contracts
- [x] bounded sample profiler
- [x] SQLite development adapter
- [x] Athena datasource adapter
- [x] SQL table + equality-join mapping
- [x] exact SQLite relationship diagnostics
- [x] DataHub MCP metadata adapter boundary
- [x] CLI
- [ ] web inspection surface
- [ ] persisted audit bundles

### v0.2 — relationship diagnostics

- [ ] cost-aware warehouse join probes
- [ ] declared vs observed relationship comparison
- [ ] query-history join frequency
- [ ] relationship confidence policy with visible inputs

### v0.3 — warehouse adapters

- [x] Athena — first production dogfood backend
- [ ] [Snowflake](https://github.com/tmusser/data-wayfinder/issues/4) — open for contribution
- [ ] [BigQuery](https://github.com/tmusser/data-wayfinder/issues/5) — open for contribution
- [ ] [Trino / Presto](https://github.com/tmusser/data-wayfinder/issues/6) — open for contribution
- [ ] [Postgres](https://github.com/tmusser/data-wayfinder/issues/7) — open for contribution
- [ ] Databricks / Spark SQL — defer until a live dogfood environment is available for stress testing

### v0.4 — agent surface

- [ ] Wayfinder MCP server
- [ ] `inspect_table`
- [ ] `inspect_field`
- [ ] `find_join_path`
- [ ] `explain_relationship_evidence`

## Design principles

1. **Evidence before inference.**
2. **Bound expensive work.**
3. **Keep catalog metadata distinct from live observations.**
4. **Make joins inspectable objects, not decorative graph edges.**
5. **Use a stable contract underneath every interface.**
6. **Prefer unknown over manufactured certainty.**
7. **The analyst remains the decision-maker.**

## Analytical stack

```text
data-wayfinder
raw tables -> understand the data surface

claim-contract
evidence -> understand what the evidence can support

chart-contract
claim -> understand whether the visual encodes it responsibly
```

These are complementary layers, not one monolithic analytics framework.

## License

MIT
