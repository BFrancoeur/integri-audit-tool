"""Raw catalog + pg_stat_statements SQL for the Full-Text & Structured Search
Behavior category.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.

Some of this category's rubric bullets (combining structured + free-text
filters, relevance ranking, safe query parsing) describe application/query
code, not schema — invisible to catalog metadata. But they leave a trace in
`pg_stat_statements` (if installed), which logs the actual normalized SQL
text the application has been running. Querying it is a plain read-only
SELECT, no different in risk from anything else this tool does; every
function below degrades gracefully (see is_pg_stat_statements_available) when
the extension isn't installed, which is common on client databases.

Caveat: pg_stat_statements only shows statements visible to the connecting
role (superuser/pg_read_all_stats sees everything; an ordinary role only sees
its own), and only top-level statements by default (not ones nested inside
PL/pgSQL functions) — so a "no matching statements found" result means "none
observed", not "none exist".
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


_IS_PG_STAT_STATEMENTS_AVAILABLE_SQL = """
    SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements';
"""

# "Free-text statement" = contains the tsquery match operator (@@).
# "Combined" = also contains JSONB containment (@>) in the same statement,
# meaning structured + free-text filtering happened in one planned query
# rather than two separate, un-composed code paths.
_FREETEXT_AND_STRUCTURED_COMBINATION_STATS_SQL = """
    SELECT
        count(*) FILTER (WHERE query ILIKE '%@@%') AS freetext_statement_count,
        count(*) FILTER (WHERE query ILIKE '%@@%' AND query ILIKE '%@>%') AS combined_statement_count
    FROM pg_stat_statements;
"""

# "Ranked" = a free-text statement that also calls ts_rank()/ts_rank_cd().
_FREETEXT_RANKING_STATS_SQL = """
    SELECT
        count(*) FILTER (WHERE query ILIKE '%@@%') AS freetext_statement_count,
        count(*) FILTER (
            WHERE query ILIKE '%@@%'
              AND (query ILIKE '%ts_rank(%' OR query ILIKE '%ts_rank_cd(%')
        ) AS ranked_statement_count
    FROM pg_stat_statements;
"""

# Raw to_tsquery() requires the caller to hand it already-valid tsquery
# syntax (operators like & | ! ()) — malformed input raises a hard error,
# unlike websearch_to_tsquery()/plainto_tsquery() which parse free-form text
# safely. Both wrapper function names contain "to_tsquery(" as a substring
# (e.g. "websearch_to_tsquery("), so they're explicitly excluded rather than
# counted as raw usage.
_RAW_TSQUERY_USAGE_SQL = """
    SELECT
        count(*) FILTER (
            WHERE query ILIKE '%to_tsquery(%'
              AND query NOT ILIKE '%websearch_to_tsquery(%'
              AND query NOT ILIKE '%plainto_tsquery(%'
        ) AS raw_tsquery_statement_count,
        (array_agg(left(query, 200)) FILTER (
            WHERE query ILIKE '%to_tsquery(%'
              AND query NOT ILIKE '%websearch_to_tsquery(%'
              AND query NOT ILIKE '%plainto_tsquery(%'
        ))[1:3] AS example_queries
    FROM pg_stat_statements;
"""


def is_pg_stat_statements_available(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute(_IS_PG_STAT_STATEMENTS_AVAILABLE_SQL)
        return cur.fetchone() is not None


def fetch_freetext_and_structured_combination_stats(conn: psycopg.Connection) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_FREETEXT_AND_STRUCTURED_COMBINATION_STATS_SQL)
        return cur.fetchone()


def fetch_freetext_ranking_stats(conn: psycopg.Connection) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_FREETEXT_RANKING_STATS_SQL)
        return cur.fetchone()


def fetch_raw_tsquery_usage(conn: psycopg.Connection) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_RAW_TSQUERY_USAGE_SQL)
        return cur.fetchone()
