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
from psycopg import sql
from psycopg.rows import dict_row

MIN_LIVE_ROWS_FOR_STATS = 20
"""Below this row count, null-fraction/distinctness estimates are too noisy
to be worth flagging — skip near-empty tables."""

MAX_DISTINCT_VALUES_FOR_ENUM_LIKE = 15
"""A text/varchar column with this few distinct values looks like it's
standing in for an enum or lookup table -- high enough to catch real status/
category fields, low enough that an ordinary free-text column (names,
descriptions) won't coincidentally qualify."""

ORPHAN_SAMPLE_LIMIT = 20
"""Rows sampled per unvalidated FK when confirming actual orphans exist --
bounded (an anti-join can be expensive on a huge table) and small enough to
give concrete examples without overwhelming the report, matching
lot_and_certification_traceability's existing sample-size convention."""

JSONB_SAMPLE_ROW_LIMIT = 5000
"""Cap on rows scanned per JSONB column when checking for empty/malformed
documents -- same value as jsonb_structure_and_governance's SAMPLE_ROW_LIMIT,
duplicated rather than imported since each category module is self-contained."""

MIN_JSONB_SAMPLE_SIZE_FOR_EMPTY_CHECK = 20
"""Below this many non-null sampled rows, an "X% are empty" signal is too
noisy on a near-empty table to be worth flagging."""

MIN_EMPTY_JSONB_FRACTION_TO_FLAG = 0.01
"""A JSONB column where at least this fraction of sampled non-null values
are an empty object/array ('{}' or '[]') looks like a write-path issue
(a form submitted with nothing filled in, a serialization bug) rather than
an occasional legitimate empty value -- low enough to catch a real pattern,
high enough that a single stray empty row in a huge table doesn't trigger it."""

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


# ---------------------------------------------------------------------------
# 06.07: CHECK-constraint coverage + enum-like free-text columns (merged --
# both SOP write-ups describe the same underlying signal: low-cardinality
# text with no CHECK, no lookup-table FK, values free to drift)
# ---------------------------------------------------------------------------
# n_distinct > 0 restricts to Postgres's *absolute-count* estimate mode (a
# negative n_distinct means "fraction of rows," i.e. high cardinality --
# the opposite of what an enum-like column looks like), same sign
# convention already documented in category 1's repeating-column-groups.
_LOW_CARDINALITY_UNGOVERNED_COLUMNS_SQL = """
    SELECT
        s.schemaname AS schema_name,
        s.tablename AS table_name,
        s.attname AS column_name,
        s.n_distinct,
        t.n_live_tup
    FROM pg_stats s
    JOIN pg_stat_user_tables t
      ON t.schemaname = s.schemaname AND t.relname = s.tablename
    JOIN information_schema.columns c
      ON c.table_schema = s.schemaname AND c.table_name = s.tablename AND c.column_name = s.attname
    WHERE s.schemaname NOT IN ('pg_catalog', 'information_schema')
      AND t.n_live_tup >= %(min_rows)s
      AND c.data_type IN ('character varying', 'text', 'character')
      AND s.n_distinct > 0
      AND s.n_distinct <= %(max_distinct_values)s
      AND NOT EXISTS (
          SELECT 1
          FROM pg_constraint con
          JOIN pg_class tc ON tc.oid = con.conrelid
          JOIN pg_namespace tn ON tn.oid = tc.relnamespace
          WHERE con.contype = 'c'
            AND tn.nspname = s.schemaname
            AND tc.relname = s.tablename
            AND pg_get_constraintdef(con.oid) ILIKE '%%' || s.attname || '%%'
      )
      AND NOT EXISTS (
          SELECT 1
          FROM information_schema.table_constraints tcc
          JOIN information_schema.key_column_usage kcu
            ON kcu.constraint_name = tcc.constraint_name AND kcu.table_schema = tcc.table_schema
          WHERE tcc.constraint_type = 'FOREIGN KEY'
            AND kcu.table_schema = s.schemaname
            AND kcu.table_name = s.tablename
            AND kcu.column_name = s.attname
      )
    ORDER BY s.schemaname, s.tablename, s.attname;
"""


def fetch_low_cardinality_ungoverned_columns(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _LOW_CARDINALITY_UNGOVERNED_COLUMNS_SQL,
            {"min_rows": MIN_LIVE_ROWS_FOR_STATS, "max_distinct_values": MAX_DISTINCT_VALUES_FOR_ENUM_LIKE},
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# 06.08: default-value audit
# ---------------------------------------------------------------------------
# Scoped to boolean/status-shaped NOT NULL columns with no DB-level DEFAULT,
# excluding primary keys -- a blanket "any NOT NULL column without a
# DEFAULT" sweep would be mostly noise (plenty of required columns, like
# email or name, have no sensible universal default and that's normal).
# Status/flag-shaped columns are the case where divergent app-layer
# defaults across multiple write paths actually cause real inconsistency.
_MISSING_DEFAULT_ON_STATUS_LIKE_COLUMNS_SQL = """
    SELECT
        c.table_schema AS schema_name,
        c.table_name,
        c.column_name,
        c.data_type
    FROM information_schema.columns c
    WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND c.is_nullable = 'NO'
      AND c.column_default IS NULL
      AND (c.data_type = 'boolean' OR c.column_name ~* '(status|state|active|enabled|flag)$')
      AND NOT EXISTS (
          SELECT 1
          FROM information_schema.table_constraints tc
          JOIN information_schema.key_column_usage kcu
            ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
          WHERE tc.constraint_type = 'PRIMARY KEY'
            AND kcu.table_schema = c.table_schema
            AND kcu.table_name = c.table_name
            AND kcu.column_name = c.column_name
      )
    ORDER BY c.table_schema, c.table_name, c.column_name;
"""


def fetch_missing_default_on_status_like_columns(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_MISSING_DEFAULT_ON_STATUS_LIKE_COLUMNS_SQL)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# 06.09: orphaned-row sampling on unvalidated foreign keys -- this
# category's first row-sampling check (the others are all pg_stats/catalog-
# only). Scoped to single-column NOT VALID FK constraints only: a VALIDATED
# constraint is enforced by Postgres itself and can't have orphans by
# construction, so sampling one would always find nothing. Deliberately
# does NOT attempt undeclared FK-shaped columns (schema_design's heuristic)
# -- guessing which table an undeclared column like customer_id "probably"
# references is a real leap with no reliable naming convention to lean on,
# and a wrong guess here means confidently reporting orphans against the
# wrong table. NOT VALID constraints already name the exact parent
# table/column with no guessing involved.
# ---------------------------------------------------------------------------
_UNVALIDATED_FK_DETAIL_SQL = """
    SELECT
        con.conname,
        n.nspname AS schema_name,
        t.relname AS table_name,
        ca.attname AS child_column,
        pn.nspname AS parent_schema,
        pt.relname AS parent_table,
        pa.attname AS parent_column
    FROM pg_constraint con
    JOIN pg_class t ON t.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    JOIN pg_attribute ca ON ca.attrelid = t.oid AND ca.attnum = con.conkey[1]
    JOIN pg_class pt ON pt.oid = con.confrelid
    JOIN pg_namespace pn ON pn.oid = pt.relnamespace
    JOIN pg_attribute pa ON pa.attrelid = pt.oid AND pa.attnum = con.confkey[1]
    WHERE con.contype = 'f'
      AND NOT con.convalidated
      AND array_length(con.conkey, 1) = 1
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
    ORDER BY n.nspname, t.relname, con.conname;
"""


def fetch_unvalidated_fk_detail(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_UNVALIDATED_FK_DETAIL_SQL)
        return cur.fetchall()


def fetch_orphaned_child_rows(
    conn: psycopg.Connection,
    schema_name: str,
    table_name: str,
    child_column: str,
    parent_schema: str,
    parent_table: str,
    parent_column: str,
) -> list:
    query = sql.SQL(
        """
        SELECT c.{child_column} AS orphaned_value
        FROM {schema}.{table} c
        WHERE c.{child_column} IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM {parent_schema}.{parent_table} p
              WHERE p.{parent_column} = c.{child_column}
          )
        LIMIT %(sample_limit)s
        """
    ).format(
        child_column=sql.Identifier(child_column),
        schema=sql.Identifier(schema_name),
        table=sql.Identifier(table_name),
        parent_schema=sql.Identifier(parent_schema),
        parent_table=sql.Identifier(parent_table),
        parent_column=sql.Identifier(parent_column),
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, {"sample_limit": ORPHAN_SAMPLE_LIMIT})
        return [row["orphaned_value"] for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# 06.02: malformed JSONB entries. Scoped to "empty object/array where data
# was expected" specifically -- the other symptoms this rubric bullet names
# (wrong types, unexpected nesting) are already covered at finer grain by
# category 2's key-type-inconsistency check; an empty document is a
# whole-document-level signal that check can't see, since it operates on
# per-key values, not the document as a whole.
# ---------------------------------------------------------------------------
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


def fetch_jsonb_columns(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_JSONB_COLUMNS_SQL)
        return cur.fetchall()


def fetch_empty_jsonb_document_stats(
    conn: psycopg.Connection, schema_name: str, table_name: str, column_name: str
) -> dict:
    query = sql.SQL(
        """
        WITH sample AS (
            SELECT {column} AS doc
            FROM {schema}.{table}
            WHERE {column} IS NOT NULL
            LIMIT %(sample_limit)s
        )
        SELECT
            count(*) FILTER (WHERE doc = '{{}}'::jsonb OR doc = '[]'::jsonb) AS empty_count,
            count(*) AS sample_size
        FROM sample;
        """
    ).format(
        column=sql.Identifier(column_name),
        schema=sql.Identifier(schema_name),
        table=sql.Identifier(table_name),
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, {"sample_limit": JSONB_SAMPLE_ROW_LIMIT})
        return cur.fetchone()
