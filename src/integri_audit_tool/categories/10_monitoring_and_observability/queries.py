"""Raw catalog + statistics SQL for the Monitoring & Observability category.

pg_stat_activity/pg_stat_user_tables/pg_settings for current-state signals —
connection saturation and long-running queries happening right now, and
tables with bloat but no recent vacuum activity. No row sampling.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.
"""

from __future__ import annotations

from datetime import timedelta

import psycopg
from psycopg.rows import dict_row

MIN_LIVE_ROWS_FOR_STATS = 20
"""Below this row count, dead-tuple ratios are too noisy to be worth flagging."""

DEAD_TUPLE_RATIO_THRESHOLD = 0.2
"""Dead-tuple fraction above which a table looks meaningfully bloated."""

VACUUM_STALENESS_THRESHOLD = timedelta(days=7)
"""How long since the last (auto)vacuum before "hasn't been addressed recently" applies."""

LONG_RUNNING_QUERY_THRESHOLD = timedelta(minutes=5)
"""How long a currently-active query has to have been running to count as long-running."""

_IS_PG_STAT_STATEMENTS_AVAILABLE_SQL = """
    SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements';
"""

_CONNECTION_SATURATION_SQL = """
    SELECT
        (SELECT count(*) FROM pg_stat_activity) AS current_connections,
        (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') AS max_connections;
"""

# Excludes our own audit connection. Query text for other roles' sessions
# requires pg_monitor/pg_read_all_stats or superuser — an ordinary role still
# sees the row (pid, duration) with an empty query, same visibility caveat as
# category 5's idle-in-transaction check.
_LONG_RUNNING_ACTIVE_QUERIES_SQL = """
    SELECT
        pid,
        usename,
        application_name,
        now() - query_start AS query_duration,
        left(coalesce(query, ''), 200) AS query
    FROM pg_stat_activity
    WHERE state = 'active'
      AND pid <> pg_backend_pid()
      AND query_start IS NOT NULL
      AND now() - query_start > %(min_duration)s
    ORDER BY query_start ASC;
"""

# Distinct from category 7's 07.04 (which flags bloat + no per-table
# autovacuum *configuration*): this checks bloat + no recent vacuum
# *activity*, regardless of configuration — a table could be perfectly
# tuned and still show this if autovacuum is failing, disabled cluster-wide,
# or the table is excluded some other way. Configuration gap vs. outcome gap.
_BLOATED_TABLES_WITHOUT_RECENT_VACUUM_SQL = """
    SELECT
        schemaname AS schema_name,
        relname AS table_name,
        n_live_tup,
        n_dead_tup,
        (n_dead_tup::numeric / GREATEST(n_live_tup, 1)) AS dead_tuple_ratio,
        last_vacuum,
        last_autovacuum
    FROM pg_stat_user_tables
    WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
      AND n_live_tup >= %(min_rows)s
      AND (n_dead_tup::numeric / GREATEST(n_live_tup, 1)) >= %(dead_tuple_ratio_threshold)s
      AND (last_vacuum IS NULL OR last_vacuum < now() - %(staleness_threshold)s)
      AND (last_autovacuum IS NULL OR last_autovacuum < now() - %(staleness_threshold)s)
    ORDER BY dead_tuple_ratio DESC;
"""


def is_pg_stat_statements_available(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute(_IS_PG_STAT_STATEMENTS_AVAILABLE_SQL)
        return cur.fetchone() is not None


def fetch_connection_saturation(conn: psycopg.Connection) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_CONNECTION_SATURATION_SQL)
        return cur.fetchone()


def fetch_long_running_active_queries(
    conn: psycopg.Connection, min_duration: timedelta = LONG_RUNNING_QUERY_THRESHOLD
) -> list[dict]:
    """min_duration is overridable (default: the real production threshold) so integration
    tests can catch a briefly-active query without actually waiting out 5 real minutes."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_LONG_RUNNING_ACTIVE_QUERIES_SQL, {"min_duration": min_duration})
        return cur.fetchall()


def fetch_bloated_tables_without_recent_vacuum(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _BLOATED_TABLES_WITHOUT_RECENT_VACUUM_SQL,
            {
                "min_rows": MIN_LIVE_ROWS_FOR_STATS,
                "dead_tuple_ratio_threshold": DEAD_TUPLE_RATIO_THRESHOLD,
                "staleness_threshold": VACUUM_STALENESS_THRESHOLD,
            },
        )
        return cur.fetchall()
