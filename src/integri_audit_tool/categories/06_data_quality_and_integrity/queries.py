"""Raw catalog + planner-statistics SQL for the Data Quality & Integrity category.

Unlike category 2 (which had to sample actual JSONB row data), most of this
category's signal is already collected by Postgres's own ANALYZE process and
exposed via `pg_stats` (per-column null fraction, distinct-value estimates)
and `pg_stat_user_tables` (live row counts) — reading it is as cheap and
catalog-only as categories 1 and 3. The trade-off: these are ANALYZE-time
*estimates* from a sample, not exhaustive counts, and a table that's never
been analyzed (no autovacuum run yet, e.g. immediately after bulk load) won't
appear in pg_stats at all — evidence text calls this out.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

MIN_LIVE_ROWS_FOR_STATS = 20
"""Below this row count, null-fraction/distinctness estimates are too noisy
to be worth flagging — skip near-empty tables."""

# Every nullable column's null_frac, for tables with enough rows to matter.
# Two checks share this: high null_frac (06.01) and never-null (06.05) are
# opposite readings of the same underlying data.
_NULLABLE_COLUMN_NULL_FRACTIONS_SQL = """
    SELECT
        s.schemaname AS schema_name,
        s.tablename AS table_name,
        s.attname AS column_name,
        s.null_frac,
        t.n_live_tup
    FROM pg_stats s
    JOIN pg_stat_user_tables t
      ON t.schemaname = s.schemaname AND t.relname = s.tablename
    JOIN information_schema.columns c
      ON c.table_schema = s.schemaname AND c.table_name = s.tablename AND c.column_name = s.attname
    WHERE s.schemaname NOT IN ('pg_catalog', 'information_schema')
      AND c.is_nullable = 'YES'
      AND t.n_live_tup >= %(min_rows)s
    ORDER BY s.schemaname, s.tablename, s.attname;
"""

# A FOREIGN KEY constraint created with NOT VALID (often to avoid locking a
# large table) that's never had VALIDATE CONSTRAINT run against it — Postgres
# enforces it for new writes but has never confirmed existing rows satisfy
# it, so orphaned references can already be sitting in the table undetected.
_UNVALIDATED_FOREIGN_KEYS_SQL = """
    SELECT
        con.conname,
        n.nspname AS schema_name,
        t.relname AS table_name,
        pg_get_constraintdef(con.oid) AS constraint_def
    FROM pg_constraint con
    JOIN pg_class t ON t.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE con.contype = 'f'
      AND NOT con.convalidated
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
    ORDER BY n.nspname, t.relname, con.conname;
"""

# Candidates for 06.04 (near-unique but not constrained): every column on a
# table with enough rows that ISN'T already covered by a single-column unique
# index/constraint. checks.py filters this down using n_distinct vs
# n_live_tup — kept in Python rather than SQL since n_distinct's sign
# (positive = absolute count, negative = fraction of rows) needs branching
# logic that's clearer as code than as a CASE expression.
_COLUMNS_WITHOUT_SINGLE_COLUMN_UNIQUE_CONSTRAINT_SQL = """
    SELECT
        s.schemaname AS schema_name,
        s.tablename AS table_name,
        s.attname AS column_name,
        s.n_distinct,
        t.n_live_tup
    FROM pg_stats s
    JOIN pg_stat_user_tables t
      ON t.schemaname = s.schemaname AND t.relname = s.tablename
    WHERE s.schemaname NOT IN ('pg_catalog', 'information_schema')
      AND t.n_live_tup >= %(min_rows)s
      AND NOT EXISTS (
          SELECT 1
          FROM pg_index idx
          JOIN pg_class tc ON tc.oid = idx.indrelid
          JOIN pg_namespace tn ON tn.oid = tc.relnamespace
          JOIN pg_attribute a ON a.attrelid = tc.oid AND a.attnum = idx.indkey[0]
          WHERE idx.indisunique
            AND idx.indnkeyatts = 1
            AND tn.nspname = s.schemaname
            AND tc.relname = s.tablename
            AND a.attname = s.attname
      )
    ORDER BY s.schemaname, s.tablename, s.attname;
"""

# Heuristic name match on common audit/change-tracking timestamp columns.
_AUDIT_TIMESTAMP_COLUMN_NULL_FRACTIONS_SQL = """
    SELECT
        s.schemaname AS schema_name,
        s.tablename AS table_name,
        s.attname AS column_name,
        s.null_frac,
        t.n_live_tup
    FROM pg_stats s
    JOIN pg_stat_user_tables t
      ON t.schemaname = s.schemaname AND t.relname = s.tablename
    WHERE s.schemaname NOT IN ('pg_catalog', 'information_schema')
      AND t.n_live_tup >= %(min_rows)s
      AND s.attname ~* '^(created|updated|modified)_at$'
      AND s.null_frac > 0
    ORDER BY s.null_frac DESC;
"""


def fetch_nullable_column_null_fractions(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_NULLABLE_COLUMN_NULL_FRACTIONS_SQL, {"min_rows": MIN_LIVE_ROWS_FOR_STATS})
        return cur.fetchall()


def fetch_unvalidated_foreign_keys(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_UNVALIDATED_FOREIGN_KEYS_SQL)
        return cur.fetchall()


def fetch_columns_without_unique_constraint(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _COLUMNS_WITHOUT_SINGLE_COLUMN_UNIQUE_CONSTRAINT_SQL, {"min_rows": MIN_LIVE_ROWS_FOR_STATS}
        )
        return cur.fetchall()


def fetch_audit_timestamp_column_null_fractions(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_AUDIT_TIMESTAMP_COLUMN_NULL_FRACTIONS_SQL, {"min_rows": MIN_LIVE_ROWS_FOR_STATS})
        return cur.fetchall()
