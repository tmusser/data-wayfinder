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
