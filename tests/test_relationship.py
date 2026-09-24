import sqlite3

from data_wayfinder.datasources import SQLiteDataSource
from data_wayfinder.service import inspect_relationship


def test_relationship_probe_finds_one_to_many_and_expansion(tmp_path):
    db = tmp_path / "demo.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE customers (customer_id INTEGER PRIMARY KEY);
            CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER);
            INSERT INTO customers VALUES (1), (2), (3), (4);
            INSERT INTO orders VALUES
              (100, 1), (101, 1), (102, 2), (103, 3), (104, 3), (105, 3);
            """
        )

    relation = inspect_relationship(
        SQLiteDataSource(db),
        "customers",
        "customer_id",
        "orders",
        "customer_id",
    )

    assert relation.cardinality == "one_to_many"
    assert relation.match_rate_left == 0.75
    assert relation.match_rate_right == 1.0
    assert relation.row_expansion == 1.75
    assert relation.evidence[0].source == "live_profile"
