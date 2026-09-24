# Enhancements Log

Running record of substantive fixes and enhancements to `data-wayfinder`, most recent
first. Each entry: what was wrong or missing, how it was found, what changed, and the PR.
Routine refactors and doc-only changes don't need an entry here — this is for anything that
changes what the tool does or what it tells you.

---

## 2026-09-24 — `sqlmap`: separate CTEs from real tables, dedupe by canonical name

**PR:** [#2](https://github.com/tmusser/data-wayfinder/pull/2)
**Found via:** dogfooding `map` against a real 10-CTE, 3-table analysis query pulled from
`feature-builder`'s `cta-testing` project — checked in as `examples/cta_identity_bridge.sql`,
the first non-toy example in the repo.

**What was wrong:**
- Names defined in a query's own `WITH` clause were listed in `tables`, indistinguishable
  from genuine warehouse tables. Since real analyst SQL is CTE-heavy almost by default, this
  made the "Tables" output noisy to the point of being misleading on anything past a toy
  query.
- The same table (or CTE) referenced under two different aliases in different scopes
  produced two separate entries instead of one — dedup keyed on `alias or name` rather than
  the table's own canonical identity.

**What changed:**
- `QueryTable.alias: str | None` → `QueryTable.aliases: list[str]` — a table can legitimately
  be referenced under more than one alias across a query.
- `QueryMap` gained a `ctes: list[QueryTable]` field, populated the same way as `tables` but
  for names defined in the query's own `WITH` clause.
- Both `map_query`'s sqlglot path and its regex fallback now dedupe by canonical name
  (collecting every alias seen onto one entry) and route `WITH`-defined names into `ctes`
  instead of `tables`.
- CLI's `map` command renders a separate "CTEs (query-scoped, not warehouse tables)" section
  when any exist.
- Two regression tests: one asserting CTEs never leak into `tables`, one asserting a
  doubly-aliased real table collapses to a single entry with both aliases.

**Flagged, not fixed (separate, pre-existing, lower priority):** the regex fallback path
(only exercised when `sqlglot` isn't importable) doesn't strip SQL comments before matching,
so a `--` comment containing the word "from" can produce a spurious table entry; its
reserved-word list is also missing `group`/`order`/`having`, so a bare `GROUP BY` right after
an unaliased `FROM` can get captured as a bogus alias. Low blast radius since `sqlglot` is a
hard runtime dependency in practice — worth a follow-up if the fallback path ever needs to be
relied on for real.
