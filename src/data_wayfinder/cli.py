from __future__ import annotations

import sqlite3
from pathlib import Path

import typer

from data_wayfinder.datasources import ProfileBudget, SQLiteDataSource
from data_wayfinder.service import inspect_relationship, inspect_table
from data_wayfinder.sqlmap import map_query

app = typer.Typer(
    help="Inspect warehouse tables, fields, and relationship evidence before analysis."
)


@app.command("inspect")
def inspect_command(
    table: str = typer.Option(..., "--table", help="Table name to inspect."),
    sqlite: Path = typer.Option(..., "--sqlite", help="SQLite database path."),
    sample_rows: int = typer.Option(5000, min=1, max=100_000),
    max_fields: int = typer.Option(100, min=1, max=500),
) -> None:
    source = SQLiteDataSource(sqlite)
    audit = inspect_table(
        source,
        table,
        budget=ProfileBudget(sample_rows=sample_rows, max_fields=max_fields),
    )
    typer.echo(audit.model_dump_json(indent=2))


@app.command("map")
def map_command(
    path: Path = typer.Argument(..., exists=True, dir_okay=False),
    dialect: str | None = typer.Option(None, "--dialect"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    query_map = map_query(path.read_text(), dialect=dialect)
    if json_output:
        typer.echo(query_map.model_dump_json(indent=2))
        return

    typer.echo("Tables")
    for table in query_map.tables:
        aliases = f" ({', '.join(table.aliases)})" if table.aliases else ""
        typer.echo(f"- {table.name}{aliases}")

    if query_map.ctes:
        typer.echo("\nCTEs (query-scoped, not warehouse tables)")
        for cte in query_map.ctes:
            aliases = f" ({', '.join(cte.aliases)})" if cte.aliases else ""
            typer.echo(f"- {cte.name}{aliases}")

    typer.echo("\nRelationships")
    if not query_map.relationships:
        typer.echo("- none")
    for relation in query_map.relationships:
        typer.echo(
            f"- {relation.left_table}.{relation.left_field} "
            f"-> {relation.right_table}.{relation.right_field} "
            f"[{relation.join_type or 'join'}]"
        )

    for warning in query_map.warnings:
        typer.echo(f"\nwarning: {warning}", err=True)


@app.command("probe-join")
def probe_join_command(
    sqlite: Path = typer.Option(..., "--sqlite", help="SQLite database path."),
    left_table: str = typer.Option(..., "--left-table"),
    left_field: str = typer.Option(..., "--left-field"),
    right_table: str = typer.Option(..., "--right-table"),
    right_field: str = typer.Option(..., "--right-field"),
    join_type: str = typer.Option("left", "--join-type"),
) -> None:
    source = SQLiteDataSource(sqlite)
    relationship = inspect_relationship(
        source,
        left_table,
        left_field,
        right_table,
        right_field,
        join_type=join_type,
    )
    typer.echo(relationship.model_dump_json(indent=2))


@app.command("demo-db")
def demo_db(
    path: Path = typer.Argument(Path("examples/demo.db")),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE customers (
              customer_id INTEGER PRIMARY KEY,
              signup_date TEXT NOT NULL,
              segment TEXT,
              country TEXT
            );

            CREATE TABLE orders (
              order_id INTEGER PRIMARY KEY,
              customer_id INTEGER NOT NULL,
              net_revenue REAL,
              created_at TEXT NOT NULL
            );

            INSERT INTO customers VALUES
              (1, '2026-01-04', 'SMB', 'US'),
              (2, '2026-01-05', 'Enterprise', 'US'),
              (3, '2026-01-06', 'SMB', 'CA'),
              (4, '2026-02-10', 'Mid-Market', 'GB');

            INSERT INTO orders VALUES
              (100, 1, 52.00, '2026-02-01'),
              (101, 1, 88.50, '2026-02-03'),
              (102, 2, 640.00, '2026-02-07'),
              (103, 3, -20.00, '2026-02-09'),
              (104, 3, 110.00, '2026-02-10'),
              (105, 3, 75.00, '2026-02-11');
            """
        )
    typer.echo(str(path))


if __name__ == "__main__":
    app()
