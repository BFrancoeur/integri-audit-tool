"""Raw catalog + statistics SQL for the Scale & Growth Readiness category.

Every bullet in this category turns out to be answerable from data Postgres
already tracks: pg_stat_statements for measured slow queries, pg_class/
pg_total_relation_size for table footprint, and pg_class.relrowsecurity for
tenant-isolation posture. No row sampling needed anywhere here.

07.04 (autovacuum tuning vs. bloat) and 07.05 (TOAST overhead from large
values) moved to the new storage-health-and-maintenance category — see that
category's __init__.py docstring for why. This category now focuses purely
on capacity/growth-trajectory questions, not storage/vacuum health.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

SLOW_QUERY_MEAN_MS_THRESHOLD = 1000
"""Mean execution time (ms) above which a query is worth surfacing as measured degradation."""

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
