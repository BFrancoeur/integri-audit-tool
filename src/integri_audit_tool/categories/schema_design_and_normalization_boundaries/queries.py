"""Raw catalog SQL for the Schema Design & Normalization Boundaries category.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

# Heuristic: columns shaped like a foreign key reference (ends in `_id`, an
# integer/uuid type) that aren't covered by any declared FOREIGN KEY
# constraint. Can't detect relationships enforced purely in application code,
# only the absence of a declared constraint for an FK-shaped column.
_FK_LIKE_COLUMNS_WITHOUT_FK_SQL = """
    SELECT
        c.table_schema AS schema_name,
        c.table_name,
        c.column_name,
        c.data_type
    FROM information_schema.columns c
    WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND c.column_name ~ '_id$'
      AND c.data_type IN ('integer', 'bigint', 'smallint', 'uuid')
      AND NOT EXISTS (
          SELECT 1
          FROM information_schema.table_constraints tc
          JOIN information_schema.key_column_usage kcu
            ON kcu.constraint_name = tc.constraint_name
           AND kcu.table_schema = tc.table_schema
          WHERE tc.constraint_type = 'FOREIGN KEY'
            AND kcu.table_schema = c.table_schema
            AND kcu.table_name = c.table_name
            AND kcu.column_name = c.column_name
      )
    ORDER BY c.table_schema, c.table_name, c.column_name;
"""

# Groups columns by name across the whole schema, normalizing away case AND
# underscores so snake_case and camelCase variants of the same concept land in
# the same group (e.g. created_at / createdAt -> "createdat"). A concept that
# shows up with inconsistent naming or inconsistent data types is evidence of
# schema drift.
#
# information_schema.columns fields are domain types (sql_identifier,
# character_data), not plain text/varchar — array_agg() over a domain type
# produces an array whose element OID psycopg doesn't have a decoder for, so
# it's returned as an undecoded wire string instead of a Python list. Casting
# to ::text before aggregating avoids that.
_COLUMNS_WITH_NAME_OR_TYPE_DRIFT_SQL = """
    SELECT
        lower(replace(c.column_name, '_', '')) AS normalized_name,
        array_agg(DISTINCT c.column_name::text ORDER BY c.column_name::text) AS observed_names,
        array_agg(DISTINCT c.data_type::text ORDER BY c.data_type::text) AS observed_types,
        array_agg(DISTINCT c.table_name::text ORDER BY c.table_name::text) AS tables
    FROM information_schema.columns c
    WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
    GROUP BY lower(replace(c.column_name, '_', ''))
    HAVING count(DISTINCT c.column_name) > 1 OR count(DISTINCT c.data_type) > 1
    ORDER BY normalized_name;
"""

_TABLES_WITHOUT_PRIMARY_KEY_SQL = """
    SELECT
        t.table_schema AS schema_name,
        t.table_name
    FROM information_schema.tables t
    WHERE t.table_type = 'BASE TABLE'
      AND t.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND NOT EXISTS (
          SELECT 1
          FROM information_schema.table_constraints tc
          WHERE tc.constraint_type = 'PRIMARY KEY'
            AND tc.table_schema = t.table_schema
            AND tc.table_name = t.table_name
      )
    ORDER BY t.table_schema, t.table_name;
"""

_PRIMARY_KEY_COLUMN_TYPES_SQL = """
    SELECT
        tc.table_schema AS schema_name,
        tc.table_name,
        c.data_type
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
    JOIN information_schema.columns c
      ON c.table_schema = kcu.table_schema
     AND c.table_name = kcu.table_name
     AND c.column_name = kcu.column_name
    WHERE tc.constraint_type = 'PRIMARY KEY'
      AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY tc.table_schema, tc.table_name;
"""


def fetch_fk_like_columns_without_fk(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_FK_LIKE_COLUMNS_WITHOUT_FK_SQL)
        return cur.fetchall()


def fetch_columns_with_name_or_type_drift(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_COLUMNS_WITH_NAME_OR_TYPE_DRIFT_SQL)
        return cur.fetchall()


def fetch_tables_without_primary_key(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_TABLES_WITHOUT_PRIMARY_KEY_SQL)
        return cur.fetchall()


def fetch_primary_key_column_types(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_PRIMARY_KEY_COLUMN_TYPES_SQL)
        return cur.fetchall()
