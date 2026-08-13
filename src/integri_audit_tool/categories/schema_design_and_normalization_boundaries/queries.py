"""Raw catalog SQL for the Schema Design & Normalization Boundaries category.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.
"""

from __future__ import annotations

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

TEXT_SHAPE_SAMPLE_LIMIT = 200
"""Rows sampled per text/varchar column when checking whether its values are
consistently numeric-/date-/list-shaped -- smaller than jsonb_structure's
5000-row SAMPLE_ROW_LIMIT since this runs once per candidate *column* across
the whole schema, not once per already-narrowed-down JSONB column."""

MIN_SAMPLE_SIZE_FOR_SHAPE_CHECK = 10
"""Below this many non-null sampled values, a shape match is too noisy to
be worth flagging -- a column with only a couple of populated rows could
look "100% numeric" by coincidence."""

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


# Powers 01.07 (repeating column groups / baked-in pivots) -- unlike the other
# queries in this file, the pattern-detection logic lives in checks.py rather
# than SQL, since grouping columns by "same type, name differs at exactly one
# token position" needs branching that's clearer as Python than as a query.
_ALL_COLUMNS_SQL = """
    SELECT
        c.table_schema AS schema_name,
        c.table_name,
        c.column_name,
        c.data_type
    FROM information_schema.columns c
    WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY c.table_schema, c.table_name, c.column_name;
"""


def fetch_all_columns(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_ALL_COLUMNS_SQL)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# 01.02: structured data stored as text
# ---------------------------------------------------------------------------
# "Inconsistent timestamp types across related tables" (the SOP's fourth
# sub-signal for this bullet) is deliberately not built here -- 01.05's
# schema-drift check already catches it: two tables with a column sharing a
# normalized name (e.g. created_at) but different types is exactly what
# _COLUMNS_WITH_NAME_OR_TYPE_DRIFT_SQL already flags, timestamp/timestamptz
# included. Building a second, narrower version of the same detection would
# be a near-duplicate check, not new coverage.

_TEXT_TYPED_COLUMNS_SQL = """
    SELECT
        c.table_schema AS schema_name,
        c.table_name,
        c.column_name
    FROM information_schema.columns c
    WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND c.data_type IN ('text', 'character varying', 'character')
    ORDER BY c.table_schema, c.table_name, c.column_name;
"""

# varchar with no length specified behaves identically to text but implies a
# bound that was never actually declared -- either give it a real length or
# use text outright.
_VARCHAR_WITHOUT_LENGTH_SQL = """
    SELECT
        c.table_schema AS schema_name,
        c.table_name,
        c.column_name
    FROM information_schema.columns c
    WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND c.data_type = 'character varying'
      AND c.character_maximum_length IS NULL
    ORDER BY c.table_schema, c.table_name, c.column_name;
"""

# money is fixed to the database's locale-dependent currency formatting and
# doesn't survive a locale change or cross-currency arithmetic cleanly --
# numeric(p,s) is the standard recommendation for monetary values.
_MONEY_TYPE_USAGE_SQL = """
    SELECT
        c.table_schema AS schema_name,
        c.table_name,
        c.column_name
    FROM information_schema.columns c
    WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND c.data_type = 'money'
    ORDER BY c.table_schema, c.table_name, c.column_name;
"""


def fetch_text_typed_columns(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_TEXT_TYPED_COLUMNS_SQL)
        return cur.fetchall()


def fetch_text_column_value_sample(
    conn: psycopg.Connection, schema_name: str, table_name: str, column_name: str
) -> list[str]:
    query = sql.SQL(
        """
        SELECT {column} AS value
        FROM {schema}.{table}
        WHERE {column} IS NOT NULL
        LIMIT %(sample_limit)s
        """
    ).format(
        column=sql.Identifier(column_name),
        schema=sql.Identifier(schema_name),
        table=sql.Identifier(table_name),
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, {"sample_limit": TEXT_SHAPE_SAMPLE_LIMIT})
        return [row["value"] for row in cur.fetchall()]


def fetch_varchar_without_length(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_VARCHAR_WITHOUT_LENGTH_SQL)
        return cur.fetchall()


def fetch_money_type_usage(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_MONEY_TYPE_USAGE_SQL)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# 01.04 extensions: cascade-behavior mismatch (folded into missing-foreign-keys)
# ---------------------------------------------------------------------------
# confdeltype = 'c' is ON DELETE CASCADE -- deleting the parent row silently
# deletes every dependent child row. The naming-heuristic filter for whether
# that looks intentional lives in checks.py (Python, not SQL) since it needs
# string-containment branching clearer as code.
_ON_DELETE_CASCADE_CONSTRAINTS_SQL = """
    SELECT
        n.nspname AS schema_name,
        t.relname AS table_name,
        con.conname,
        pt.relname AS parent_table_name
    FROM pg_constraint con
    JOIN pg_class t ON t.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    JOIN pg_class pt ON pt.oid = con.confrelid
    WHERE con.contype = 'f'
      AND con.confdeltype = 'c'
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
    ORDER BY n.nspname, t.relname, con.conname;
"""


def fetch_on_delete_cascade_constraints(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_ON_DELETE_CASCADE_CONSTRAINTS_SQL)
        return cur.fetchall()
