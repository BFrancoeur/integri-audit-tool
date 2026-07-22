"""Integration coverage for category 7's raw SQL against a real Postgres instance.

Unlike tests/unit/categories/test_07_scale_and_growth_readiness.py (canned
rows), these validate that the SQL in queries.py is actually correct. Marked
`integration`; run explicitly with `pytest -m integration` (requires Docker).

Table names are prefixed `c7_` to avoid colliding with other categories' test
tables in the shared, session-scoped test container. This file enables
pg_stat_statements itself so it can run standalone in any order.

pg_stat_user_tables counters (used for bloat/scan-count checks) are only
guaranteed current after `SELECT pg_stat_force_next_flush()` (PG15+) — without
it, a just-executed DELETE/scan may not be reflected yet.
"""

import importlib

import pytest

queries = importlib.import_module("integri_audit_tool.categories.07_scale_and_growth_readiness.queries")

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _enable_pg_stat_statements(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")


def test_fetch_slow_queries_detects_measured_slow_statement(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("SELECT pg_sleep(1.1)")

    rows = queries.fetch_slow_queries(pg_conn)

    assert any("pg_sleep" in r["query"] for r in rows)
    slow_row = next(r for r in rows if "pg_sleep" in r["query"])
    assert slow_row["mean_exec_time"] > 1000


def test_fetch_slow_queries_excludes_own_introspection_query(pg_conn):
    rows = queries.fetch_slow_queries(pg_conn)

    assert not any("pg_stat_statements" in r["query"] for r in rows)


def test_fetch_largest_tables_returns_sorted_nonempty_results(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c7_footprint (id serial PRIMARY KEY, data text)")
        cur.execute("INSERT INTO c7_footprint (data) SELECT repeat('x', 100) FROM generate_series(1, 500)")

    rows = queries.fetch_largest_tables(pg_conn)

    assert len(rows) > 0
    assert len(rows) <= 10
    sizes = [r["total_bytes"] for r in rows]
    assert sizes == sorted(sizes, reverse=True)
    assert all(size > 0 for size in sizes)


def test_fetch_tenant_columns_without_rls_distinguishes_secured_table(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c7_invoices (id serial PRIMARY KEY, tenant_id int)")
        cur.execute("CREATE TABLE c7_secure_invoices (id serial PRIMARY KEY, tenant_id int)")
        cur.execute("ALTER TABLE c7_secure_invoices ENABLE ROW LEVEL SECURITY")

    rows = queries.fetch_tenant_columns_without_rls(pg_conn)

    assert any(r["table_name"] == "c7_invoices" for r in rows)
    assert not any(r["table_name"] == "c7_secure_invoices" for r in rows)


def test_fetch_high_bloat_tables_without_tuning_detects_dead_tuples(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c7_sessions (id serial PRIMARY KEY, data text)")
        cur.execute("INSERT INTO c7_sessions (data) SELECT 'x' FROM generate_series(1, 100)")
        cur.execute("DELETE FROM c7_sessions WHERE id <= 50")
        cur.execute("SELECT pg_stat_force_next_flush()")

    rows = queries.fetch_high_bloat_tables_without_tuning(pg_conn)

    row = next((r for r in rows if r["table_name"] == "c7_sessions"), None)
    assert row is not None
    assert row["dead_tuple_ratio"] > 0.2


def test_fetch_high_bloat_tables_without_tuning_excludes_tuned_table(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE c7_tuned_sessions (id serial PRIMARY KEY, data text) "
            "WITH (autovacuum_vacuum_scale_factor = 0.05)"
        )
        cur.execute("INSERT INTO c7_tuned_sessions (data) SELECT 'x' FROM generate_series(1, 100)")
        cur.execute("DELETE FROM c7_tuned_sessions WHERE id <= 50")
        cur.execute("SELECT pg_stat_force_next_flush()")

    rows = queries.fetch_high_bloat_tables_without_tuning(pg_conn)

    assert not any(r["table_name"] == "c7_tuned_sessions" for r in rows)


def test_fetch_large_jsonb_on_hot_tables_detects_toast_usage(pg_conn):
    # repeat('x', N) compresses to almost nothing under Postgres's automatic
    # TOAST compression and wouldn't actually exercise out-of-line storage —
    # use high-entropy (incompressible) values instead, and enough of them to
    # clear MIN_TOAST_TABLE_BYTES (1MB).
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c7_products (id serial PRIMARY KEY, attrs jsonb)")
        cur.execute(
            "INSERT INTO c7_products (attrs) "
            "SELECT jsonb_build_object('description', "
            "(SELECT string_agg(md5(random()::text), '') FROM generate_series(1, 100))) "
            "FROM generate_series(1, 400)"
        )
        cur.execute("ANALYZE c7_products")
        for _ in range(15):
            cur.execute("SELECT * FROM c7_products")
        cur.execute("SELECT pg_stat_force_next_flush()")

    rows = queries.fetch_large_jsonb_on_hot_tables(pg_conn)

    row = next((r for r in rows if r["table_name"] == "c7_products"), None)
    assert row is not None
    assert row["toast_bytes"] >= 1_000_000
    assert row["access_count"] >= 10
