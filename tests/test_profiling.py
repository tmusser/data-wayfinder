import sqlite3

from data_wayfinder.datasources import ProfileBudget, SQLiteDataSource
from data_wayfinder.profiling import profile_table


def test_sqlite_profile(tmp_path):
    db = tmp_path / "demo.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE customers (
              customer_id INTEGER PRIMARY KEY,
              segment TEXT,
              revenue REAL
            );
            INSERT INTO customers VALUES
              (1, 'SMB', 10.0),
              (2, 'SMB', 20.0),
              (3, 'Enterprise', NULL);
            """
        )

    audit = profile_table(
        SQLiteDataSource(db),
        "customers",
        ProfileBudget(sample_rows=100),
    )

    assert audit.profile.rows == 3
    assert audit.profile.sampled_rows == 3
    assert audit.fields["customer_id"].inferred_role == "identifier"
    assert audit.fields["revenue"].profile.null_count == 1
    assert audit.fields["revenue"].profile.max == 20.0
    assert audit.fields["segment"].profile.distinct_count == 2
