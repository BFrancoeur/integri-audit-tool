"""Raw catalog/stats SQL for the Indexing Strategy category.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

_UNUSED_INDEXES_SQL = """
    SELECT
        s.schemaname AS schema_name,
        s.relname AS table_name,
        s.indexrelname AS index_name,
        s.idx_scan,
        pg_relation_size(s.indexrelid) AS index_size_bytes
    FROM pg_stat_user_indexes s
    JOIN pg_index i ON i.indexrelid = s.indexrelid
    WHERE s.idx_scan = 0
      AND NOT i.indisprimary
      AND NOT i.indisunique
    ORDER BY pg_relation_size(s.indexrelid) DESC;
"""

# Heuristic: text-matches pg_indexes.indexdef rather than resolving access
# methods via pg_am/pg_attribute. Simple and cheap; can produce false negatives
# for expression indexes where the column name doesn't appear verbatim.
_JSONB_COLUMNS_WITHOUT_GIN_SQL = """
    SELECT
        c.table_schema AS schema_name,
        c.table_name,
        c.column_name
    FROM information_schema.columns c
    WHERE c.data_type = 'jsonb'
      AND c.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND NOT EXISTS (
          SELECT 1
          FROM pg_indexes pi
          WHERE pi.schemaname = c.table_schema
            AND pi.tablename = c.table_name
            AND pi.indexdef ILIKE '%USING gin%'
            AND pi.indexdef ILIKE '%' || c.column_name || '%'
      )
    ORDER BY c.table_schema, c.table_name, c.column_name;
"""

# Groups indexes on the same table that share a leading column as
# "possible overlap" candidates for manual review, rather than proving full
# column-list containment (which needs indkey prefix comparison).
_INDEXES_SHARING_LEADING_COLUMN_SQL = """
    SELECT
        t.relname AS table_name,
        a.attname AS leading_column,
        array_agg(i.indexrelid::regclass::text ORDER BY i.indexrelid) AS index_names,
        array_agg(pg_get_indexdef(i.indexrelid) ORDER BY i.indexrelid) AS index_defs
    FROM pg_index i
    JOIN pg_class t ON t.oid = i.indrelid
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = i.indkey[0]
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
    GROUP BY t.relname, a.attname
    HAVING count(*) > 1
    ORDER BY t.relname, a.attname;
"""


def fetch_unused_indexes(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_UNUSED_INDEXES_SQL)
        return cur.fetchall()


def fetch_jsonb_columns_without_gin(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_JSONB_COLUMNS_WITHOUT_GIN_SQL)
        return cur.fetchall()


def fetch_indexes_sharing_leading_column(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_INDEXES_SHARING_LEADING_COLUMN_SQL)
        return cur.fetchall()
