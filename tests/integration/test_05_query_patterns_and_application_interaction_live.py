"""Integration coverage for category 5's raw SQL against a real Postgres instance.

Unlike tests/unit/categories/test_05_query_patterns_and_application_interaction.py
(canned rows), these validate that the SQL in queries.py is actually correct.
Marked `integration`; run explicitly with `pytest -m integration` (requires Docker).

Table names are prefixed `c5_` to avoid colliding with other categories' test
tables in the shared, session-scoped test container. This file enables
pg_stat_statements itself (rather than relying on category 4's tests having
already done so) so it can run standalone in any order.
"""

import importlib

import psycopg
import pytest

queries = importlib.import_module(
    "integri_audit_tool.categories.query_patterns_and_application_interaction.queries"
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _enable_pg_stat_statements(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")


def test_fetch_n_plus_one_candidates_flags_frequently_called_point_lookup(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c5_orders (id serial PRIMARY KEY, customer_id int)")
        cur.execute("INSERT INTO c5_orders (customer_id) SELECT g FROM generate_series(1, 5) g")
        for _ in range(150):
            cur.execute("SELECT * FROM c5_orders WHERE customer_id = %s", (1,))

    rows = queries.fetch_n_plus_one_candidates(pg_conn)

    assert any("c5_orders" in r["query"] for r in rows)


def test_fetch_n_plus_one_candidates_excludes_join_queries(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c5_join_a (id serial PRIMARY KEY)")
        cur.execute("CREATE TABLE c5_join_b (id serial PRIMARY KEY, a_id int REFERENCES c5_join_a(id))")
        cur.execute("INSERT INTO c5_join_a DEFAULT VALUES")
        for _ in range(150):
            cur.execute(
                "SELECT * FROM c5_join_a a JOIN c5_join_b b ON b.a_id = a.id WHERE a.id = %s", (1,)
            )

    rows = queries.fetch_n_plus_one_candidates(pg_conn)

    assert not any("c5_join_a" in r["query"] for r in rows)


def test_fetch_offset_pagination_usage_detects_offset_queries(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c5_articles (id serial PRIMARY KEY)")
        cur.execute("SELECT * FROM c5_articles ORDER BY id OFFSET 10 LIMIT 20")

    stats = queries.fetch_offset_pagination_usage(pg_conn)

    assert stats["matched_statement_count"] >= 1
    assert any("OFFSET" in q for q in (stats["example_queries"] or []))


def test_fetch_idle_in_transaction_sessions_detects_open_transaction(pg_conn, postgres_container):
    dsn = postgres_container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    idle_conn = psycopg.connect(dsn)
    try:
        with idle_conn.cursor() as cur:
            cur.execute("SELECT 1")
        # deliberately not committed - leaves this session idle in transaction

        rows = queries.fetch_idle_in_transaction_sessions(pg_conn)

        assert any(r["pid"] == idle_conn.info.backend_pid for r in rows)
    finally:
        idle_conn.close()


def test_fetch_slow_query_monitoring_status_reports_pg_stat_statements_enabled(pg_conn):
    status = queries.fetch_slow_query_monitoring_status(pg_conn)

    assert status["pg_stat_statements_enabled"] is True
    assert isinstance(status["log_min_duration_statement"], str)
