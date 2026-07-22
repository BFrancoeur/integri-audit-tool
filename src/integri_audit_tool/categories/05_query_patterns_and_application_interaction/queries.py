"""Raw catalog + pg_stat_statements/pg_stat_activity SQL for the Query
Patterns & Application Interaction category.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.

Two of this category's rubric bullets (N+1 patterns, OFFSET pagination) lean
on pg_stat_statements, same as category 4 — the functions that use it degrade
gracefully when it isn't installed. `pg_stat_activity`/`pg_settings`-based
checks need no extension at all; they're always available.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

_IS_PG_STAT_STATEMENTS_AVAILABLE_SQL = """
    SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements';
"""

_N_PLUS_ONE_CALL_THRESHOLD = 100
"""Minimum call count before a simple point-lookup query is worth surfacing as
an N+1 candidate. Arbitrary but conservative — well above what a handful of
legitimate page loads would produce."""

# Heuristic: a query shaped like a single-row point lookup (has a WHERE
# clause, no JOIN, averages close to one row per call) that's been called an
# unusually large number of times is a *candidate* for an N+1 pattern —
# pg_stat_statements aggregates across all callers with no per-request
# grouping, so this can't prove N+1, only surface queries worth checking.
_N_PLUS_ONE_CANDIDATES_SQL = """
    SELECT
        left(query, 200) AS query,
        calls,
        rows,
        (rows::numeric / NULLIF(calls, 0)) AS avg_rows_per_call
    FROM pg_stat_statements
    WHERE query ILIKE '%%WHERE%%'
      AND query NOT ILIKE '%%JOIN%%'
      AND calls > %(call_threshold)s
      AND (rows::numeric / NULLIF(calls, 0)) BETWEEN 0 AND 1.5
    ORDER BY calls DESC
    LIMIT 5;
"""

# Column aliases here deliberately avoid the substring "offset" (e.g. not
# `offset_statement_count`) — this query itself gets recorded in
# pg_stat_statements once run, and ILIKE '%OFFSET%' would then match its own
# stored query text via the alias name, self-polluting the result on every
# subsequent audit.
_OFFSET_PAGINATION_USAGE_SQL = """
    SELECT
        count(*) AS matched_statement_count,
        (array_agg(left(query, 200)))[1:3] AS example_queries
    FROM pg_stat_statements
    WHERE query ILIKE '%OFFSET%';
"""

# Excludes our own audit connection. Seeing another session's `query` text
# requires pg_monitor/pg_read_all_stats or superuser — an ordinary role sees
# the row (pid, state, xact_start) but an empty query for sessions it doesn't
# own, so this can under-report detail without under-reporting existence.
_IDLE_IN_TRANSACTION_SESSIONS_SQL = """
    SELECT
        pid,
        usename,
        application_name,
        now() - xact_start AS transaction_duration,
        left(coalesce(query, ''), 200) AS last_query
    FROM pg_stat_activity
    WHERE state = 'idle in transaction'
      AND pid <> pg_backend_pid()
    ORDER BY xact_start ASC;
"""

_SLOW_QUERY_MONITORING_STATUS_SQL = """
    SELECT
        EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS pg_stat_statements_enabled,
        EXISTS (SELECT 1 FROM pg_settings WHERE name LIKE 'auto_explain.%') AS auto_explain_loaded,
        (SELECT setting FROM pg_settings WHERE name = 'log_min_duration_statement') AS log_min_duration_statement;
"""


def is_pg_stat_statements_available(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute(_IS_PG_STAT_STATEMENTS_AVAILABLE_SQL)
        return cur.fetchone() is not None


def fetch_n_plus_one_candidates(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_N_PLUS_ONE_CANDIDATES_SQL, {"call_threshold": _N_PLUS_ONE_CALL_THRESHOLD})
        return cur.fetchall()


def fetch_offset_pagination_usage(conn: psycopg.Connection) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_OFFSET_PAGINATION_USAGE_SQL)
        return cur.fetchone()


def fetch_idle_in_transaction_sessions(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_IDLE_IN_TRANSACTION_SESSIONS_SQL)
        return cur.fetchall()


def fetch_slow_query_monitoring_status(conn: psycopg.Connection) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_SLOW_QUERY_MONITORING_STATUS_SQL)
        return cur.fetchone()
