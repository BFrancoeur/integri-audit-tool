"""Integration coverage for category 10's raw SQL against a real Postgres instance.

Unlike tests/unit/categories/test_10_monitoring_and_observability.py (canned
rows), these validate that the SQL in queries.py is actually correct. Marked
`integration`; run explicitly with `pytest -m integration` (requires Docker).

Table names are prefixed `c10_` to avoid colliding with other categories'
test tables in the shared, session-scoped test container.
"""

import importlib
import threading
import time
from datetime import timedelta

import psycopg
import pytest

queries = importlib.import_module("integri_audit_tool.categories.10_monitoring_and_observability.queries")

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _enable_pg_stat_statements(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")


def test_is_pg_stat_statements_available_true_once_extension_created(pg_conn):
    assert queries.is_pg_stat_statements_available(pg_conn) is True


def test_fetch_connection_saturation_returns_sane_values(pg_conn):
    result = queries.fetch_connection_saturation(pg_conn)

    assert result["current_connections"] >= 1
    assert result["max_connections"] > 0


def test_fetch_long_running_active_queries_detects_active_query(pg_conn, postgres_container):
    dsn = postgres_container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")

    def run_slow_query() -> None:
        conn = psycopg.connect(dsn, autocommit=True)
        with conn.cursor() as cur:
            cur.execute("SELECT pg_sleep(3)")
        conn.close()

    thread = threading.Thread(target=run_slow_query)
    thread.start()
    time.sleep(1)  # give the query time to start and show as 'active'

    rows = queries.fetch_long_running_active_queries(pg_conn, min_duration=timedelta(0))

    thread.join()

    assert any("pg_sleep" in (r["query"] or "") for r in rows)


def test_fetch_bloated_tables_without_recent_vacuum_detects_bloat(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c10_sessions (id serial PRIMARY KEY, data text)")
        cur.execute("INSERT INTO c10_sessions (data) SELECT 'x' FROM generate_series(1, 100)")
        cur.execute("DELETE FROM c10_sessions WHERE id <= 50")
        cur.execute("SELECT pg_stat_force_next_flush()")

    rows = queries.fetch_bloated_tables_without_recent_vacuum(pg_conn)

    row = next((r for r in rows if r["table_name"] == "c10_sessions"), None)
    assert row is not None
    assert row["dead_tuple_ratio"] > 0.2
    assert row["last_vacuum"] is None


def test_fetch_bloated_tables_without_recent_vacuum_excludes_recently_vacuumed(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c10_recent (id serial PRIMARY KEY, data text)")
        cur.execute("INSERT INTO c10_recent (data) SELECT 'x' FROM generate_series(1, 100)")
        cur.execute("DELETE FROM c10_recent WHERE id <= 50")
        cur.execute("VACUUM c10_recent")
        cur.execute("SELECT pg_stat_force_next_flush()")

    rows = queries.fetch_bloated_tables_without_recent_vacuum(pg_conn)

    assert not any(r["table_name"] == "c10_recent" for r in rows)
