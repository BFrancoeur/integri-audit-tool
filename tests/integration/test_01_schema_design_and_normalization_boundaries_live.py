"""Integration coverage for category 1's raw SQL against a real Postgres instance.

Unlike tests/unit/categories/test_01_schema_design_and_normalization_boundaries.py
(canned rows), these validate that the SQL in queries.py is actually correct.
Marked `integration`; run explicitly with `pytest -m integration` (requires Docker).

Table names are prefixed `c1_` to avoid colliding with other categories' test
tables in the shared, session-scoped test container.
"""

import importlib

import pytest

queries = importlib.import_module(
    "integri_audit_tool.categories.schema_design_and_normalization_boundaries.queries"
)

pytestmark = pytest.mark.integration


def test_fetch_fk_like_columns_without_fk_flags_unconstrained_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c1_orders (id serial PRIMARY KEY, customer_id integer)")
        cur.execute(
            "CREATE TABLE c1_order_items (id serial PRIMARY KEY, order_id integer REFERENCES c1_orders(id))"
        )

    rows = queries.fetch_fk_like_columns_without_fk(pg_conn)

    assert any(r["table_name"] == "c1_orders" and r["column_name"] == "customer_id" for r in rows)
    assert not any(r["table_name"] == "c1_order_items" and r["column_name"] == "order_id" for r in rows)


def test_fetch_columns_with_name_or_type_drift_flags_inconsistent_concept(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c1_table_a (id serial PRIMARY KEY, created_at timestamptz)")
        cur.execute('CREATE TABLE c1_table_b (id serial PRIMARY KEY, "createdAt" text)')

    rows = queries.fetch_columns_with_name_or_type_drift(pg_conn)

    drifted = next((r for r in rows if r["normalized_name"] == "createdat"), None)
    assert drifted is not None
    assert set(drifted["observed_names"]) == {"created_at", "createdAt"}
    assert set(drifted["observed_types"]) == {"timestamp with time zone", "text"}


def test_fetch_tables_without_primary_key_flags_pk_less_table(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c1_logs (id integer, message text)")

    rows = queries.fetch_tables_without_primary_key(pg_conn)

    assert any(r["table_name"] == "c1_logs" for r in rows)


def test_fetch_primary_key_column_types_reports_types_per_table(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c1_pktype_uuid (id uuid PRIMARY KEY, name text)")
        cur.execute("CREATE TABLE c1_pktype_int (id serial PRIMARY KEY)")

    rows = queries.fetch_primary_key_column_types(pg_conn)
    types = {r["table_name"]: r["data_type"] for r in rows}

    assert types.get("c1_pktype_uuid") == "uuid"
    assert types.get("c1_pktype_int") == "integer"
