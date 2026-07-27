"""Integration coverage for category 3's raw SQL against a real Postgres instance.

Unlike tests/unit/categories/test_03_indexing_strategy.py (which tests the
interpretation logic against canned rows), these tests validate that the SQL
in queries.py is actually correct. Marked `integration`; run explicitly with
`pytest -m integration` (requires Docker).
"""

import importlib

import pytest

queries = importlib.import_module("integri_audit_tool.categories.indexing_strategy.queries")

pytestmark = pytest.mark.integration


def test_fetch_unused_indexes_flags_an_unscanned_index(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE widgets (id serial PRIMARY KEY, sku text)")
        cur.execute("CREATE INDEX idx_widgets_sku ON widgets (sku)")

    rows = queries.fetch_unused_indexes(pg_conn)

    assert any(r["index_name"] == "idx_widgets_sku" for r in rows)
    assert not any(r["index_name"].endswith("_pkey") for r in rows)


def test_fetch_jsonb_columns_without_gin_flags_unindexed_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE products (id serial PRIMARY KEY, attributes jsonb)")

    rows = queries.fetch_jsonb_columns_without_gin(pg_conn)

    assert any(r["table_name"] == "products" and r["column_name"] == "attributes" for r in rows)


def test_fetch_indexes_sharing_leading_column_detects_overlap(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE orders (id serial PRIMARY KEY, customer_id int, created_at timestamptz)")
        cur.execute("CREATE INDEX idx_orders_customer ON orders (customer_id)")
        cur.execute("CREATE INDEX idx_orders_customer_created ON orders (customer_id, created_at)")

    rows = queries.fetch_indexes_sharing_leading_column(pg_conn)

    assert any(r["table_name"] == "orders" and r["leading_column"] == "customer_id" for r in rows)
