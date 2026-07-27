"""Integration coverage for category 11's raw SQL against a real Postgres instance.

Unlike tests/unit/categories/test_11_documentation_and_institutional_knowledge.py
(canned rows), these validate that the SQL in queries.py is actually correct.
Marked `integration`; run explicitly with `pytest -m integration` (requires
Docker).

Table names are prefixed `c11_` to avoid colliding with other categories'
test tables in the shared, session-scoped test container, except where
testing recognition of a specific registry table name.
"""

import importlib

import pytest

queries = importlib.import_module(
    "integri_audit_tool.categories.documentation_and_institutional_knowledge.queries"
)

pytestmark = pytest.mark.integration


def test_fetch_table_documentation_coverage_counts_correctly(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c11_documented (id serial PRIMARY KEY)")
        cur.execute("COMMENT ON TABLE c11_documented IS 'A documented table for testing'")
        cur.execute("CREATE TABLE c11_undocumented (id serial PRIMARY KEY)")

    coverage = queries.fetch_table_documentation_coverage(pg_conn)

    assert coverage["total_tables"] >= 2
    assert coverage["documented_tables"] >= 1


def test_fetch_undocumented_jsonb_columns_distinguishes_documented_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c11_products (id serial PRIMARY KEY, attrs jsonb)")
        cur.execute("CREATE TABLE c11_orders (id serial PRIMARY KEY, meta jsonb)")
        cur.execute("COMMENT ON COLUMN c11_orders.meta IS 'Order metadata, flexible per payment provider'")

    rows = queries.fetch_undocumented_jsonb_columns(pg_conn)

    assert any(r["table_name"] == "c11_products" and r["column_name"] == "attrs" for r in rows)
    assert not any(r["table_name"] == "c11_orders" and r["column_name"] == "meta" for r in rows)


def test_fetch_jsonb_and_registry_presence_detects_jsonb_without_registry(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c11_widgets (id serial PRIMARY KEY, attrs jsonb)")

    presence = queries.fetch_jsonb_and_registry_presence(pg_conn)

    assert presence["has_jsonb_columns"] is True
    assert presence["has_registry_table"] is False


def test_fetch_jsonb_and_registry_presence_detects_registry_table(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE attribute_definitions (id serial PRIMARY KEY, key text)")

    presence = queries.fetch_jsonb_and_registry_presence(pg_conn)

    assert presence["has_registry_table"] is True
