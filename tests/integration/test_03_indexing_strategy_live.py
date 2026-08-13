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


def test_fetch_unindexed_foreign_keys_flags_fk_with_no_supporting_index(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE idx_test_customers (id serial PRIMARY KEY)")
        cur.execute(
            "CREATE TABLE idx_test_invoices (id serial PRIMARY KEY, "
            "customer_id int REFERENCES idx_test_customers(id))"
        )
        cur.execute("CREATE TABLE idx_test_invoice_lines (id serial PRIMARY KEY, "
                    "invoice_id int REFERENCES idx_test_invoices(id))")
        cur.execute("CREATE INDEX idx_test_invoice_lines_invoice_id ON idx_test_invoice_lines (invoice_id)")

    rows = queries.fetch_unindexed_foreign_keys(pg_conn)

    assert any(r["table_name"] == "idx_test_invoices" and r["column_name"] == "customer_id" for r in rows)
    assert not any(r["table_name"] == "idx_test_invoice_lines" for r in rows)


def test_fetch_seq_scan_heavy_tables_detects_dominant_seq_scans(pg_conn):
    # A fixed ~100-byte text value stays well under TOAST's ~2KB inline
    # threshold, so pg_relation_size() (main relation only, not TOAST)
    # actually reflects the row count -- enough rows to clear
    # MIN_TABLE_BYTES_FOR_SEQ_SCAN_CHECK (10MB) via row count alone.
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE idx_test_events (id serial PRIMARY KEY, data text)")
        cur.execute("INSERT INTO idx_test_events (data) SELECT repeat('x', 100) FROM generate_series(1, 150000)")
        for _ in range(15):
            cur.execute("SELECT count(*) FROM idx_test_events")
        cur.execute("SELECT pg_stat_force_next_flush()")

    rows = queries.fetch_seq_scan_heavy_tables(pg_conn)

    row = next((r for r in rows if r["table_name"] == "idx_test_events"), None)
    assert row is not None
    assert row["seq_scan"] >= queries.MIN_SEQ_SCAN_COUNT


def test_fetch_composite_indexes_returns_declared_column_order(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE idx_test_orders (id serial PRIMARY KEY, customer_id int, created_at timestamptz)")
        cur.execute("CREATE INDEX idx_test_orders_composite ON idx_test_orders (customer_id, created_at)")

    rows = queries.fetch_composite_indexes(pg_conn)

    row = next((r for r in rows if r["index_name"] == "idx_test_orders_composite"), None)
    assert row is not None
    assert row["index_columns"] == ["customer_id", "created_at"]


def test_fetch_queries_mentioning_second_column_not_leading_counts_matches(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
        cur.execute(
            "CREATE TABLE idx_test_shipments (id serial PRIMARY KEY, customer_id int, ship_date date, note text)"
        )
        cur.execute("SELECT note FROM idx_test_shipments WHERE ship_date = '2026-01-01'")

    count = queries.fetch_queries_mentioning_second_column_not_leading(
        pg_conn, "idx_test_shipments", "customer_id", "ship_date"
    )

    assert count >= 1


def test_fetch_high_selectivity_columns_without_index_flags_unindexed_high_cardinality_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE idx_test_shipments2 (id serial PRIMARY KEY, external_ref text)")
        cur.execute(
            "INSERT INTO idx_test_shipments2 (external_ref) "
            "SELECT 'ref-' || g FROM generate_series(1, 2000) g"
        )
        cur.execute("ANALYZE idx_test_shipments2")

    rows = queries.fetch_high_selectivity_columns_without_index(pg_conn)

    assert any(r["table_name"] == "idx_test_shipments2" and r["column_name"] == "external_ref" for r in rows)
    assert not any(r["table_name"] == "idx_test_shipments2" and r["column_name"] == "id" for r in rows)


def test_fetch_jsonb_range_query_candidate_count_matches_range_comparison(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
        cur.execute("CREATE TABLE idx_test_products (id serial PRIMARY KEY, attributes jsonb)")
        cur.execute("SELECT id FROM idx_test_products WHERE (attributes->>'weight')::numeric > 10")

    count = queries.fetch_jsonb_range_query_candidate_count(pg_conn, "attributes")

    assert count >= 1


def test_fetch_high_write_tables_with_many_indexes_flags_table_over_thresholds(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE idx_test_high_write (id serial PRIMARY KEY, a int, b int, c int, d int, e int)")
        for col in ("a", "b", "c", "d", "e"):
            cur.execute(f"CREATE INDEX idx_test_high_write_{col} ON idx_test_high_write ({col})")
        cur.execute(
            "INSERT INTO idx_test_high_write (a, b, c, d, e) "
            "SELECT g, g, g, g, g FROM generate_series(1, 150000) g"
        )
        cur.execute("SELECT pg_stat_force_next_flush()")

    rows = queries.fetch_high_write_tables_with_many_indexes(pg_conn)

    row = next((r for r in rows if r["table_name"] == "idx_test_high_write"), None)
    assert row is not None
    assert row["index_count"] >= queries.MIN_INDEX_COUNT_FOR_AMPLIFICATION_CONCERN


def test_fetch_non_partial_indexes_on_flag_columns_flags_full_boolean_index(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE idx_test_users (id serial PRIMARY KEY, active boolean)")
        cur.execute("CREATE INDEX idx_test_users_active ON idx_test_users (active)")
        cur.execute(
            "CREATE TABLE idx_test_orders2 (id serial PRIMARY KEY, shipped boolean)"
        )
        cur.execute(
            "CREATE INDEX idx_test_orders2_shipped_partial ON idx_test_orders2 (shipped) WHERE shipped = false"
        )

    rows = queries.fetch_non_partial_indexes_on_flag_columns(pg_conn)

    assert any(r["index_name"] == "idx_test_users_active" for r in rows)
    assert not any(r["index_name"] == "idx_test_orders2_shipped_partial" for r in rows)
