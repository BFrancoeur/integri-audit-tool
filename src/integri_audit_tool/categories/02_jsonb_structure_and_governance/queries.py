"""Raw SQL for the JSONB Structure & Governance category.

Unlike categories 1 and 3, this category has to look at actual JSONB row
*data* (keys, value types), not just catalog metadata — so most queries here
take a specific (schema, table, column) and are built with psycopg.sql for
safe identifier interpolation, run against a bounded row sample rather than
the whole table.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.
"""

from __future__ import annotations

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

SAMPLE_ROW_LIMIT = 5000
"""Cap on rows scanned per JSONB column, to bound cost on large tables."""

_JSONB_COLUMNS_SQL = """
    SELECT
        c.table_schema AS schema_name,
        c.table_name,
        c.column_name
    FROM information_schema.columns c
    WHERE c.data_type = 'jsonb'
      AND c.table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY c.table_schema, c.table_name, c.column_name;
"""

# Heuristic: a table is treated as having "no validation layer" for a JSONB
# column if there's no CHECK constraint whose definition mentions the column
# name, and no non-internal trigger at all on the table. Coarse (a trigger
# could exist for something unrelated to this column) but a reasonable signal
# given only read-only catalog access.
_JSONB_COLUMNS_WITHOUT_VALIDATION_SQL = """
    SELECT
        c.table_schema AS schema_name,
        c.table_name,
        c.column_name
    FROM information_schema.columns c
    WHERE c.data_type = 'jsonb'
      AND c.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND NOT EXISTS (
          SELECT 1
          FROM pg_constraint con
          JOIN pg_class t ON t.oid = con.conrelid
          JOIN pg_namespace n ON n.oid = t.relnamespace
          WHERE con.contype = 'c'
            AND n.nspname = c.table_schema
            AND t.relname = c.table_name
            AND pg_get_constraintdef(con.oid) ILIKE '%' || c.column_name || '%'
      )
      AND NOT EXISTS (
          SELECT 1
          FROM pg_trigger tr
          JOIN pg_class t ON t.oid = tr.tgrelid
          JOIN pg_namespace n ON n.oid = t.relnamespace
          WHERE NOT tr.tgisinternal
            AND n.nspname = c.table_schema
            AND t.relname = c.table_name
      )
    ORDER BY c.table_schema, c.table_name, c.column_name;
"""


def fetch_jsonb_columns(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_JSONB_COLUMNS_SQL)
        return cur.fetchall()


def fetch_jsonb_columns_without_validation(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_JSONB_COLUMNS_WITHOUT_VALIDATION_SQL)
        return cur.fetchall()


def fetch_key_naming_variants(
    conn: psycopg.Connection, schema_name: str, table_name: str, column_name: str
) -> list[dict]:
    """Groups a column's observed top-level JSONB keys case/underscore-insensitively,
    flagging groups with more than one raw spelling (e.g. diameter_in / diameterIn).
    """
    query = sql.SQL(
        """
        WITH sample AS (
            SELECT {column} AS doc
            FROM {schema}.{table}
            WHERE {column} IS NOT NULL
            LIMIT %(sample_limit)s
        ),
        keys AS (
            SELECT DISTINCT k.key_name
            FROM sample
            CROSS JOIN LATERAL jsonb_object_keys(sample.doc) AS k(key_name)
        )
        SELECT
            lower(replace(key_name, '_', '')) AS normalized_key,
            array_agg(DISTINCT key_name::text ORDER BY key_name::text) AS observed_keys
        FROM keys
        GROUP BY lower(replace(key_name, '_', ''))
        HAVING count(DISTINCT key_name) > 1
        ORDER BY normalized_key;
        """
    ).format(
        column=sql.Identifier(column_name),
        schema=sql.Identifier(schema_name),
        table=sql.Identifier(table_name),
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, {"sample_limit": SAMPLE_ROW_LIMIT})
        return cur.fetchall()


def fetch_key_type_inconsistencies(
    conn: psycopg.Connection, schema_name: str, table_name: str, column_name: str
) -> list[dict]:
    """For each top-level key, flags keys whose value type (jsonb_typeof) varies
    across the sampled rows (e.g. numeric in some rows, text in others).
    """
    query = sql.SQL(
        """
        WITH sample AS (
            SELECT {column} AS doc
            FROM {schema}.{table}
            WHERE {column} IS NOT NULL
            LIMIT %(sample_limit)s
        ),
        kv AS (
            SELECT e.key AS key_name, jsonb_typeof(e.value) AS value_type
            FROM sample
            CROSS JOIN LATERAL jsonb_each(sample.doc) AS e(key, value)
        )
        SELECT
            key_name,
            array_agg(DISTINCT value_type::text ORDER BY value_type::text) AS observed_types,
            count(*) AS occurrences
        FROM kv
        GROUP BY key_name
        HAVING count(DISTINCT value_type) > 1
        ORDER BY key_name;
        """
    ).format(
        column=sql.Identifier(column_name),
        schema=sql.Identifier(schema_name),
        table=sql.Identifier(table_name),
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, {"sample_limit": SAMPLE_ROW_LIMIT})
        return cur.fetchall()
