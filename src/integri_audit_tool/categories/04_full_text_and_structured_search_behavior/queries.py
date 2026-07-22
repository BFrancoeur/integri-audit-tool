"""Raw catalog SQL for the Full-Text & Structured Search Behavior category.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

_TSVECTOR_COLUMNS_SQL = """
    SELECT
        c.table_schema AS schema_name,
        c.table_name,
        c.column_name
    FROM information_schema.columns c
    WHERE c.data_type = 'tsvector'
      AND c.table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY c.table_schema, c.table_name, c.column_name;
"""

# Heuristic: text-matches pg_indexes.indexdef for a GIN or GiST index
# mentioning the column, rather than resolving access methods via
# pg_am/pg_attribute. Simple and cheap; can produce false negatives for
# expression indexes where the column name doesn't appear verbatim.
_TSVECTOR_COLUMNS_WITHOUT_FULLTEXT_INDEX_SQL = """
    SELECT
        c.table_schema AS schema_name,
        c.table_name,
        c.column_name
    FROM information_schema.columns c
    WHERE c.data_type = 'tsvector'
      AND c.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND NOT EXISTS (
          SELECT 1
          FROM pg_indexes pi
          WHERE pi.schemaname = c.table_schema
            AND pi.tablename = c.table_name
            AND (pi.indexdef ILIKE '%USING gin%' OR pi.indexdef ILIKE '%USING gist%')
            AND pi.indexdef ILIKE '%' || c.column_name || '%'
      )
    ORDER BY c.table_schema, c.table_name, c.column_name;
"""

# A tsvector column is considered "kept in sync" if it's a STORED generated
# column (attgenerated = 's') — Postgres maintains it automatically — or if
# the table has at least one non-internal trigger (heuristic: assumed to be
# maintaining it, same coarse assumption as category 2's validation-layer
# check). Anything else is manually populated by application code with no
# enforced sync mechanism, and can silently drift from its source columns.
_TSVECTOR_COLUMNS_WITHOUT_SYNC_MECHANISM_SQL = """
    SELECT
        c.table_schema AS schema_name,
        c.table_name,
        c.column_name
    FROM information_schema.columns c
    JOIN pg_namespace n ON n.nspname = c.table_schema
    JOIN pg_class t ON t.relname = c.table_name AND t.relnamespace = n.oid
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attname = c.column_name
    WHERE c.data_type = 'tsvector'
      AND c.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND a.attgenerated <> 's'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_trigger tr
          WHERE NOT tr.tgisinternal
            AND tr.tgrelid = t.oid
      )
    ORDER BY c.table_schema, c.table_name, c.column_name;
"""


def fetch_tsvector_columns(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_TSVECTOR_COLUMNS_SQL)
        return cur.fetchall()


def fetch_tsvector_columns_without_fulltext_index(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_TSVECTOR_COLUMNS_WITHOUT_FULLTEXT_INDEX_SQL)
        return cur.fetchall()


def fetch_tsvector_columns_without_sync_mechanism(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_TSVECTOR_COLUMNS_WITHOUT_SYNC_MECHANISM_SQL)
        return cur.fetchall()
