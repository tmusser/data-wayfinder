from data_wayfinder.sqlmap import map_query


SQL = """
SELECT c.customer_id, o.order_id
FROM analytics.customers c
LEFT JOIN fact.orders o
  ON c.customer_id = o.customer_id
"""


def test_query_map_extracts_tables_and_join():
    result = map_query(SQL, dialect="snowflake")
    names = {table.name for table in result.tables}
    assert "analytics.customers" in names
    assert "fact.orders" in names

    assert len(result.relationships) == 1
    relation = result.relationships[0]
    assert relation.left_field == "customer_id"
    assert relation.right_field == "customer_id"
    assert relation.evidence[0].source == "query_sql"


CTE_SQL = """
WITH recent_customers AS (
    SELECT c.customer_id, c.signup_date
    FROM analytics.customers c
    WHERE c.signup_date >= '2026-01-01'
),
recent_orders AS (
    SELECT o.order_id, o.customer_id
    FROM fact.orders o
    JOIN recent_customers rc ON rc.customer_id = o.customer_id
)
SELECT ro.order_id
FROM recent_orders ro
JOIN fact.orders o2 ON o2.order_id = ro.order_id
"""


def test_query_map_excludes_ctes_from_tables():
    result = map_query(CTE_SQL, dialect="snowflake")

    table_names = {table.name for table in result.tables}
    cte_names = {cte.name for cte in result.ctes}

    # real warehouse tables only in `tables`
    assert table_names == {"analytics.customers", "fact.orders"}
    # query-scoped CTEs only in `ctes`, never in `tables`
    assert cte_names == {"recent_customers", "recent_orders"}
    assert "recent_customers" not in table_names
    assert "recent_orders" not in table_names


def test_query_map_dedupes_same_table_referenced_with_different_aliases():
    result = map_query(CTE_SQL, dialect="snowflake")

    orders = next(table for table in result.tables if table.name == "fact.orders")
    # fact.orders is referenced twice, once as `o` and once as `o2` -- one entry, both aliases
    assert set(orders.aliases) == {"o", "o2"}
    assert len([t for t in result.tables if t.name == "fact.orders"]) == 1
