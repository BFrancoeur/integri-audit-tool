"""Raw catalog + row-level SQL for the Lot & Certification Traceability category.

Every "lot/cert" concept here is a heuristic name match (no universal schema
convention exists across client databases) — the same approach category 1's
FK-shaped-column check and category 7's tenant-column check already use for
naming heuristics, and category 6's near-unique/null-fraction checks already
use for planner-statistics heuristics. What's different here: findings need
to name the *specific* affected lot/serial values, not just a count or a
percentage (see checks.py) — this data is high-stakes for suppliers and their
buyers, so several queries here scan real row data directly (GROUP BY/HAVING,
a NULL-filtered sample) rather than only reading pg_stats estimates. Lot/
batch tables are typically not high-row-count tables like a transactions log,
so an unindexed full scan is an acceptable cost tradeoff for the itemized
detail it buys — noted here rather than silently assumed.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.
"""

from __future__ import annotations

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

LOT_SAMPLE_LIMIT = 20
"""Cap on how many specific lot/serial values a finding names directly —
enough to be actionable without dumping an unbounded list into a report."""

MIN_LIVE_ROWS_FOR_STATS = 20
"""Below this row count, null-fraction estimates (pg_stats) are too noisy to
be worth flagging — same threshold category 6 uses for the same reason."""

_LOT_COLUMN_NAME_PATTERN = "(lot_number|lot_no|heat_number|batch_number|serial_number)"
_CERT_NAME_PATTERN = "cert"

_HAS_LOT_OR_CERTIFICATION_SIGNAL_SQL = f"""
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
          AND (
              column_name ~* '{_LOT_COLUMN_NAME_PATTERN}'
              OR column_name ~* '{_CERT_NAME_PATTERN}'
              OR table_name ~* '(cert|conformance|mtc)'
          )
    ) AS has_signal;
"""

_LOT_SHAPED_COLUMN_NULL_FRACTIONS_SQL = f"""
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
      AND s.attname ~* '{_LOT_COLUMN_NAME_PATTERN}'
    ORDER BY s.null_frac DESC;
"""

# A lot/heat/batch/serial column paired with a same-table column that looks
# like it should link to a certification record (name matches "cert") but has
# no declared FOREIGN KEY constraint — the pairing this category's check 2
# samples orphaned rows from.
_LOT_TABLES_WITH_UNCONSTRAINED_CERT_LINK_SQL = f"""
    SELECT DISTINCT
        lot_col.table_schema AS schema_name,
        lot_col.table_name,
        lot_col.column_name AS lot_column,
        link_col.column_name AS link_column
    FROM information_schema.columns lot_col
    JOIN information_schema.columns link_col
      ON link_col.table_schema = lot_col.table_schema
     AND link_col.table_name = lot_col.table_name
    WHERE lot_col.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND lot_col.column_name ~* '{_LOT_COLUMN_NAME_PATTERN}'
      AND link_col.column_name ~* '{_CERT_NAME_PATTERN}'
      AND NOT EXISTS (
          SELECT 1
          FROM information_schema.table_constraints tc
          JOIN information_schema.key_column_usage kcu
            ON kcu.constraint_name = tc.constraint_name
           AND kcu.table_schema = tc.table_schema
          WHERE tc.constraint_type = 'FOREIGN KEY'
            AND kcu.table_schema = link_col.table_schema
            AND kcu.table_name = link_col.table_name
            AND kcu.column_name = link_col.column_name
      )
    ORDER BY schema_name, table_name;
"""

_LOT_COLUMNS_WITHOUT_UNIQUE_CONSTRAINT_SQL = f"""
    SELECT DISTINCT
        c.table_schema AS schema_name,
        c.table_name,
        c.column_name AS lot_column
    FROM information_schema.columns c
    WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND c.column_name ~* '{_LOT_COLUMN_NAME_PATTERN}'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_index idx
          JOIN pg_class tc ON tc.oid = idx.indrelid
          JOIN pg_namespace tn ON tn.oid = tc.relnamespace
          JOIN pg_attribute a ON a.attrelid = tc.oid AND a.attnum = idx.indkey[0]
          WHERE idx.indisunique
            AND idx.indnkeyatts = 1
            AND tn.nspname = c.table_schema
            AND tc.relname = c.table_name
            AND a.attname = c.column_name
      )
    ORDER BY schema_name, table_name;
"""

_CERT_JSONB_COLUMNS_WITHOUT_VALIDATION_SQL = f"""
    SELECT
        c.table_schema AS schema_name,
        c.table_name,
        c.column_name
    FROM information_schema.columns c
    WHERE c.data_type = 'jsonb'
      AND c.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND c.column_name ~* '{_CERT_NAME_PATTERN}'
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


def has_lot_or_certification_signal(conn: psycopg.Connection) -> bool:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_HAS_LOT_OR_CERTIFICATION_SIGNAL_SQL)
        return cur.fetchone()["has_signal"]


def fetch_lot_shaped_column_null_fractions(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_LOT_SHAPED_COLUMN_NULL_FRACTIONS_SQL, {"min_rows": MIN_LIVE_ROWS_FOR_STATS})
        return cur.fetchall()


def fetch_lot_tables_with_unconstrained_cert_link(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_LOT_TABLES_WITH_UNCONSTRAINED_CERT_LINK_SQL)
        return cur.fetchall()


def fetch_lots_with_unlinked_certification(
    conn: psycopg.Connection, schema_name: str, table_name: str, lot_column: str, link_column: str
) -> list[dict]:
    """Samples lot values from rows where the certification-link column is
    NULL, capped at LOT_SAMPLE_LIMIT, alongside the true total via a window
    function so a truncated sample can still report an accurate count."""
    # Rows missing the lot number itself too (not just the cert link) are
    # excluded here, not just uncounted — there's no lot number to name in a
    # finding about it, and check_lot_columns_poorly_populated already covers
    # that row from the "missing identifier" angle.
    query = sql.SQL(
        """
        SELECT {lot_column} AS lot_value, COUNT(*) OVER() AS total_unlinked
        FROM {schema}.{table}
        WHERE {link_column} IS NULL
          AND {lot_column} IS NOT NULL
        ORDER BY {lot_column}
        LIMIT %(sample_limit)s;
        """
    ).format(
        lot_column=sql.Identifier(lot_column),
        link_column=sql.Identifier(link_column),
        schema=sql.Identifier(schema_name),
        table=sql.Identifier(table_name),
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, {"sample_limit": LOT_SAMPLE_LIMIT})
        return cur.fetchall()


def fetch_lot_columns_without_unique_constraint(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_LOT_COLUMNS_WITHOUT_UNIQUE_CONSTRAINT_SQL)
        return cur.fetchall()


def fetch_duplicate_lot_values(
    conn: psycopg.Connection, schema_name: str, table_name: str, lot_column: str
) -> list[dict]:
    """Exact duplicates (GROUP BY/HAVING), not a pg_stats estimate — lot
    tables are small enough that a direct scan is worth the itemized
    accuracy over an approximate signal."""
    query = sql.SQL(
        """
        SELECT {lot_column} AS lot_value, COUNT(*) AS occurrence_count
        FROM {schema}.{table}
        WHERE {lot_column} IS NOT NULL
        GROUP BY {lot_column}
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC, {lot_column}
        LIMIT %(sample_limit)s;
        """
    ).format(
        lot_column=sql.Identifier(lot_column),
        schema=sql.Identifier(schema_name),
        table=sql.Identifier(table_name),
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, {"sample_limit": LOT_SAMPLE_LIMIT})
        return cur.fetchall()


def fetch_cert_jsonb_columns_without_validation(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_CERT_JSONB_COLUMNS_WITHOUT_VALIDATION_SQL)
        return cur.fetchall()
