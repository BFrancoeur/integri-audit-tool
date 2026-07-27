"""Raw catalog + statistics SQL for the Scale & Growth Readiness category.

Every bullet in this category turns out to be answerable from data Postgres
already tracks: pg_stat_statements for measured slow queries, pg_class/
pg_total_relation_size for table footprint, pg_class.relrowsecurity for
tenant-isolation posture, pg_stat_user_tables for autovacuum/bloat signals,
and each table's TOAST relation size for large-JSONB overhead. No row
sampling needed anywhere here.

The JSONB/TOAST check originally used pg_stats.avg_width to spot "large"
values, on the assumption a big average width means big stored values. That's
backwards for exactly the rows that matter: once a value is large enough to
actually get TOASTed out-of-line, the in-row datum ANALYZE measures shrinks to
a TOAST pointer (~18 bytes) or a compressed-if-still-inline blob — either way
avg_width goes *down*, not up, precisely when out-of-line storage is
happening. Confirmed via integration testing with genuinely large,
incompressible values. Measuring the TOAST relation's own size instead
(pg_total_relation_size(reltoastrelid)) sidesteps this entirely: it's a
direct measurement of how much data is actually being stored out-of-line,
not an inference from a statistic that hides the effect.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

MIN_LIVE_ROWS_FOR_STATS = 20
"""Below this row count, dead-tuple ratios are too noisy to be worth flagging."""

SLOW_QUERY_MEAN_MS_THRESHOLD = 1000
"""Mean execution time (ms) above which a query is worth surfacing as measured degradation."""

DEAD_TUPLE_RATIO_THRESHOLD = 0.2
"""Dead-tuple fraction above which a table looks like autovacuum isn't keeping up."""

MIN_TOAST_TABLE_BYTES = 1_000_000
"""TOAST relation size above which out-of-line JSONB storage looks like it's happening at
meaningful scale, not just the odd oversized row."""

MIN_ACCESS_COUNT = 10
"""Minimum idx_scan + seq_scan before a table counts as actually being read, not just present."""

_IS_PG_STAT_STATEMENTS_AVAILABLE_SQL = """
    SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements';
"""

# Excludes statements that reference pg_stat_statements/pg_catalog/
# information_schema — this tool's own introspection queries (this one
# included) would otherwise be eligible to show up in its own slow-query
# results on a subsequent run.
_SLOW_QUERIES_SQL = """
    SELECT
        left(query, 200) AS query,
        calls,
        mean_exec_time,
        max_exec_time
    FROM pg_stat_statements
    WHERE mean_exec_time > %(mean_ms_threshold)s
      AND query NOT ILIKE '%%pg_stat_statements%%'
      AND query NOT ILIKE '%%pg_catalog%%'
      AND query NOT ILIKE '%%information_schema%%'
    ORDER BY mean_exec_time DESC
    LIMIT 10;
"""

_LARGEST_TABLES_SQL = """
    SELECT
        n.nspname AS schema_name,
        c.relname AS table_name,
        pg_total_relation_size(c.oid) AS total_bytes
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'r'
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
    ORDER BY pg_total_relation_size(c.oid) DESC
    LIMIT 10;
"""

# Heuristic name match on common tenant/organization-scoping columns.
# relrowsecurity=false means no RLS policy is enforced at the DB level for
# that table — doesn't prove queries leak across tenants (app-level
# filtering could still be correct), just that Postgres's own safety net
# isn't engaged.
_TENANT_COLUMNS_WITHOUT_RLS_SQL = """
    SELECT DISTINCT
        n.nspname AS schema_name,
        t.relname AS table_name
    FROM information_schema.columns c
    JOIN pg_namespace n ON n.nspname = c.table_schema
    JOIN pg_class t ON t.relname = c.table_name AND t.relnamespace = n.oid
    WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND c.column_name ~* '^(tenant_id|organization_id|org_id|account_id|workspace_id)$'
      AND t.relkind = 'r'
      AND NOT t.relrowsecurity
    ORDER BY n.nspname, t.relname;
"""

# A table with significant dead-tuple bloat and no per-table autovacuum
# overrides (reloptions IS NULL) is relying entirely on cluster-wide
# defaults despite evidence they aren't keeping up with its write/update
# pattern. Can't detect cluster-wide ALTER SYSTEM tuning this way, only
# per-table reloptions — a disclosed limitation, not a full picture.
_HIGH_BLOAT_WITHOUT_TUNING_SQL = """
    SELECT
        t.schemaname AS schema_name,
        t.relname AS table_name,
        t.n_live_tup,
        t.n_dead_tup,
        (t.n_dead_tup::numeric / GREATEST(t.n_live_tup, 1)) AS dead_tuple_ratio
    FROM pg_stat_user_tables t
    JOIN pg_class c ON c.oid = t.relid
    WHERE t.schemaname NOT IN ('pg_catalog', 'information_schema')
      AND t.n_live_tup >= %(min_rows)s
      AND c.reloptions IS NULL
      AND (t.n_dead_tup::numeric / GREATEST(t.n_live_tup, 1)) >= %(dead_tuple_ratio_threshold)s
    ORDER BY dead_tuple_ratio DESC;
"""

# Measures each table's TOAST relation directly rather than inferring size
# from pg_stats.avg_width (see module docstring for why that's unreliable).
# Restricted to tables that actually have a jsonb column, since large text
# columns would TOAST too but aren't what this bullet asks about.
_LARGE_JSONB_TOAST_USAGE_SQL = """
    SELECT
        n.nspname AS schema_name,
        c.relname AS table_name,
        pg_total_relation_size(toast.oid) AS toast_bytes,
        (t.idx_scan + t.seq_scan) AS access_count
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_class toast ON toast.oid = c.reltoastrelid
    JOIN pg_stat_user_tables t ON t.relid = c.oid
    WHERE c.relkind = 'r'
      AND c.reltoastrelid <> 0
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND EXISTS (
          SELECT 1
          FROM information_schema.columns col
          WHERE col.table_schema = n.nspname
            AND col.table_name = c.relname
            AND col.data_type = 'jsonb'
      )
      AND pg_total_relation_size(toast.oid) >= %(min_toast_bytes)s
      AND (t.idx_scan + t.seq_scan) >= %(min_access_count)s
    ORDER BY toast_bytes DESC;
"""


def is_pg_stat_statements_available(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute(_IS_PG_STAT_STATEMENTS_AVAILABLE_SQL)
        return cur.fetchone() is not None


def fetch_slow_queries(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_SLOW_QUERIES_SQL, {"mean_ms_threshold": SLOW_QUERY_MEAN_MS_THRESHOLD})
        return cur.fetchall()


def fetch_largest_tables(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_LARGEST_TABLES_SQL)
        return cur.fetchall()


def fetch_tenant_columns_without_rls(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_TENANT_COLUMNS_WITHOUT_RLS_SQL)
        return cur.fetchall()


def fetch_high_bloat_tables_without_tuning(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _HIGH_BLOAT_WITHOUT_TUNING_SQL,
            {"min_rows": MIN_LIVE_ROWS_FOR_STATS, "dead_tuple_ratio_threshold": DEAD_TUPLE_RATIO_THRESHOLD},
        )
        return cur.fetchall()


def fetch_large_jsonb_on_hot_tables(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _LARGE_JSONB_TOAST_USAGE_SQL,
            {"min_toast_bytes": MIN_TOAST_TABLE_BYTES, "min_access_count": MIN_ACCESS_COUNT},
        )
        return cur.fetchall()
