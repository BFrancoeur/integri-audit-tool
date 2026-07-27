"""Raw catalog SQL for the Documentation & Institutional Knowledge category.

Everything here reads pg_description (via obj_description()/col_description())
and pg_class — the only form of "documentation" visible from inside the
database at all is COMMENT ON TABLE/COLUMN. External documentation (a wiki,
an ERD tool, a README in the app repo) is invisible to a DB connection, so
absence of in-database comments is evidence, not proof, that nothing is
documented anywhere — checks.py's evidence text says so explicitly.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

# Heuristic names for a companion table that would document JSONB structure
# (valid keys, types, meaning) — the kind of thing that would let a new
# engineer understand the shape without reverse-engineering it from data.
KNOWN_JSONB_REGISTRY_TABLE_NAMES = [
    "attribute_definitions",
    "attribute_registry",
    "attribute_schema",
    "schema_registry",
    "field_registry",
    "field_definitions",
    "jsonb_schema",
    "json_schema_registry",
    "metadata_registry",
]

_TABLE_DOCUMENTATION_COVERAGE_SQL = """
    SELECT
        count(*) AS total_tables,
        count(*) FILTER (WHERE obj_description(c.oid, 'pg_class') IS NOT NULL) AS documented_tables
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'r'
      AND n.nspname NOT IN ('pg_catalog', 'information_schema');
"""

_UNDOCUMENTED_JSONB_COLUMNS_SQL = """
    SELECT
        c.table_schema AS schema_name,
        c.table_name,
        c.column_name
    FROM information_schema.columns c
    JOIN pg_namespace n ON n.nspname = c.table_schema
    JOIN pg_class t ON t.relname = c.table_name AND t.relnamespace = n.oid
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attname = c.column_name
    WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND c.data_type = 'jsonb'
      AND col_description(t.oid, a.attnum) IS NULL
    ORDER BY c.table_schema, c.table_name, c.column_name;
"""

_JSONB_AND_REGISTRY_PRESENCE_SQL = """
    SELECT
        EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE data_type = 'jsonb'
              AND table_schema NOT IN ('pg_catalog', 'information_schema')
        ) AS has_jsonb_columns,
        EXISTS (
            SELECT 1
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r'
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
              AND lower(c.relname) = ANY(%(known_names)s)
        ) AS has_registry_table;
"""


def fetch_table_documentation_coverage(conn: psycopg.Connection) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_TABLE_DOCUMENTATION_COVERAGE_SQL)
        return cur.fetchone()


def fetch_undocumented_jsonb_columns(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_UNDOCUMENTED_JSONB_COLUMNS_SQL)
        return cur.fetchall()


def fetch_jsonb_and_registry_presence(conn: psycopg.Connection) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_JSONB_AND_REGISTRY_PRESENCE_SQL, {"known_names": KNOWN_JSONB_REGISTRY_TABLE_NAMES})
        return cur.fetchone()
