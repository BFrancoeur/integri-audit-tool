"""Raw catalog/stats SQL for the Indexing Strategy category.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.

Three checks added from the SOP merge (2026-08-03) -- unindexed foreign
keys, sequential-scan-heavy tables, and composite-index column-order
mismatches -- are folded into 03.01's existing check_unused_indexes/
"unused-indexes" slug rather than authored as new bullets: 03.01's own
rubric text already spans "unused indexes" *and* "unindexed filters," and
all three describe the same underlying question (do the indexes that exist
actually match how the table is queried) from different angles, the same
way 08.04 already bundles three PII/SSL findings under one slug.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

MIN_TABLE_BYTES_FOR_SEQ_SCAN_CHECK = 10_000_000
"""Below this size, Postgres's planner is usually correct to prefer a
sequential scan over an index scan -- flagging seq-scan dominance only
matters once a table is large enough that the difference is real."""

MIN_SEQ_SCAN_COUNT = 10
"""Minimum recorded sequential scans before a table's scan pattern is
worth flagging -- avoids noise from a handful of one-off admin queries."""

MIN_ROWS_FOR_SELECTIVITY_CHECK = 1_000
"""Below this row count, n_distinct-based selectivity is too noisy to be
worth flagging -- matches this tool's other pg_stats-driven checks (e.g.
data_quality's MIN_LIVE_ROWS_FOR_STATS), scaled up since an unindexed
column only matters once a table is big enough for a sequential scan to
actually cost something."""

HIGH_SELECTIVITY_RATIO_THRESHOLD = 0.9
"""A column where at least this fraction of rows hold a distinct value
looks like an equality/range/join/sort candidate worth an index -- doesn't
confirm the column is actually filtered on (that needs query-log access
this check doesn't have), which is why it's capped at LOW severity."""

MIN_WRITE_COUNT_FOR_AMPLIFICATION_CHECK = 100_000
"""Minimum lifetime inserts+updates+deletes before a table's write volume
is high enough that extra index-maintenance overhead is worth flagging."""

MIN_INDEX_COUNT_FOR_AMPLIFICATION_CONCERN = 6
"""More indexes than this on one table is unusual enough, combined with
high write volume, to flag as a write-amplification concern -- an ordinary
table with a PK plus a couple of lookup indexes stays well under this."""

FLAG_COLUMN_NAME_PATTERN = r"(status|state|active|enabled|flag|deleted)$"
"""Same boolean/status-flag naming convention already used by
data_quality_and_integrity's missing-default check -- these are the
columns most likely to have a heavily skewed value distribution where a
partial index would meaningfully narrow index size."""

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


# Single-column FK constraints only -- matches this codebase's existing
# heuristic-FK conventions elsewhere (schema_design's FK-shaped-column
# check, this category's own leading-column-overlap check), and covers the
# overwhelming majority of real-world FKs. A composite FK with no matching
# composite index is a real but rarer gap this doesn't attempt to catch.
_UNINDEXED_FOREIGN_KEYS_SQL = """
    SELECT
        n.nspname AS schema_name,
        t.relname AS table_name,
        a.attname AS column_name,
        con.conname AS constraint_name
    FROM pg_constraint con
    JOIN pg_class t ON t.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = con.conkey[1]
    WHERE con.contype = 'f'
      AND array_length(con.conkey, 1) = 1
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND NOT EXISTS (
          SELECT 1
          FROM pg_index idx
          WHERE idx.indrelid = con.conrelid
            AND idx.indkey[0] = con.conkey[1]
      )
    ORDER BY n.nspname, t.relname, a.attname;
"""

# Deliberately catalog/stats-only, no pg_stat_statements dependency: a
# table's own seq_scan/idx_scan counters already say whether it's being
# scanned sequentially far more than it's being indexed into, which is the
# actual signal this check needs -- pg_stat_statements would only add which
# specific query text is responsible, not whether the pattern exists at all.
_SEQ_SCAN_HEAVY_TABLES_SQL = """
    SELECT
        schemaname AS schema_name,
        relname AS table_name,
        seq_scan,
        seq_tup_read,
        coalesce(idx_scan, 0) AS idx_scan,
        pg_relation_size(relid) AS table_bytes
    FROM pg_stat_user_tables
    WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
      AND pg_relation_size(relid) >= %(min_table_bytes)s
      AND seq_scan >= %(min_seq_scan_count)s
      AND seq_scan > coalesce(idx_scan, 0)
    ORDER BY seq_tup_read DESC;
"""

# Composite (2+ column) indexes only -- a single-column index has no
# "order" to mismatch. unnest()...WITH ORDINALITY preserves indkey's
# declared column order, the same way pg_get_indexdef() would display it.
_COMPOSITE_INDEXES_SQL = """
    SELECT
        n.nspname AS schema_name,
        t.relname AS table_name,
        ic.relname AS index_name,
        array_agg(a.attname ORDER BY k.ord) AS index_columns
    FROM pg_index i
    JOIN pg_class ic ON ic.oid = i.indexrelid
    JOIN pg_class t ON t.oid = i.indrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) ON true
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND array_length(i.indkey, 1) >= 2
    GROUP BY n.nspname, t.relname, ic.relname
    ORDER BY n.nspname, t.relname, ic.relname;
"""

_IS_PG_STAT_STATEMENTS_AVAILABLE_SQL = """
    SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements';
"""

# 03.03: high-selectivity columns with no supporting index at all (not just
# no leading-column index -- any index, since a column indexed only as a
# trailing composite member still gets some benefit). Restricted to types
# that are actually plausible filter/join/sort/equality candidates --
# boolean/jsonb/bytea/array columns are excluded even if technically
# high-cardinality, since they're not what this rubric bullet is asking
# about. n_distinct sign convention (positive = absolute count, negative =
# fraction of rows) is resolved in Python, same as data_quality's
# near-unique check -- clearer as branching code than a SQL CASE.
_HIGH_SELECTIVITY_COLUMN_CANDIDATE_TYPES = [
    "integer",
    "bigint",
    "smallint",
    "numeric",
    "uuid",
    "date",
    "timestamp without time zone",
    "timestamp with time zone",
    "character varying",
    "text",
    "character",
]

_HIGH_SELECTIVITY_COLUMNS_WITHOUT_INDEX_SQL = """
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
      AND c.data_type = ANY(%(candidate_types)s)
      AND NOT EXISTS (
          SELECT 1
          FROM pg_index idx
          JOIN pg_class tc ON tc.oid = idx.indrelid
          JOIN pg_namespace tn ON tn.oid = tc.relnamespace
          JOIN pg_attribute a ON a.attrelid = tc.oid AND a.attnum = ANY(idx.indkey::int2[])
          WHERE tn.nspname = s.schemaname
            AND tc.relname = s.tablename
            AND a.attname = s.attname
      )
    ORDER BY s.schemaname, s.tablename, s.attname;
"""

# 03.05: heuristic text match, same shape and same caveats as
# _QUERIES_MENTIONING_SECOND_COLUMN_NOT_LEADING_SQL above -- looks for the
# JSONB column name followed (loosely, not adjacently) by a ->> or #>>
# extraction operator, combined with a comparison operator or BETWEEN
# anywhere in the same statement. Can't confirm the extracted value is
# actually being range-compared rather than just displayed; deliberately
# capped at LOW severity in checks.py for the same reason.
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

_JSONB_RANGE_QUERY_CANDIDATE_COUNT_SQL = """
    SELECT count(*) AS matched_statement_count
    FROM pg_stat_statements
    WHERE (query ILIKE '%%' || %(column_name)s || '%%->>%%' OR query ILIKE '%%' || %(column_name)s || '%%#>>%%')
      AND (query LIKE '%%>%%' OR query LIKE '%%<%%' OR query ILIKE '%%between%%');
"""

# 03.06: pure catalog + stats, no pg_stat_statements dependency -- a
# table's own write counters plus how many indexes exist on it already say
# whether every write is paying to maintain an unusually large number of
# indexes, the same "cheap, catalog-only" shape as 03.01's seq-scan check.
_HIGH_WRITE_TABLES_WITH_MANY_INDEXES_SQL = """
    SELECT
        t.schemaname AS schema_name,
        t.relname AS table_name,
        (t.n_tup_ins + t.n_tup_upd + t.n_tup_del) AS write_count,
        idx.index_count
    FROM pg_stat_user_tables t
    JOIN (
        SELECT indrelid, count(*) AS index_count
        FROM pg_index
        GROUP BY indrelid
    ) idx ON idx.indrelid = t.relid
    WHERE t.schemaname NOT IN ('pg_catalog', 'information_schema')
      AND (t.n_tup_ins + t.n_tup_upd + t.n_tup_del) >= %(min_write_count)s
      AND idx.index_count >= %(min_index_count)s
    ORDER BY (t.n_tup_ins + t.n_tup_upd + t.n_tup_del) DESC;
"""

# 03.07: pg_indexes text heuristic -- a boolean or status/flag-named leading
# column with no WHERE clause in its own index definition (i.e. not already
# partial) is a plausible partial-index candidate. Doesn't confirm the
# actual value distribution is skewed (that would need pg_stats.most_common_
# freqs on top of this), which is why it's a candidate list, not a proven
# finding -- capped at LOW severity in checks.py.
_NON_PARTIAL_INDEXES_ON_FLAG_COLUMNS_SQL = """
    SELECT
        n.nspname AS schema_name,
        t.relname AS table_name,
        ic.relname AS index_name,
        a.attname AS column_name,
        pg_get_indexdef(i.indexrelid) AS index_def
    FROM pg_index i
    JOIN pg_class ic ON ic.oid = i.indexrelid
    JOIN pg_class t ON t.oid = i.indrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = i.indkey[0]
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND i.indpred IS NULL
      AND (a.atttypid = 'boolean'::regtype OR a.attname ~* %(flag_column_pattern)s)
    ORDER BY n.nspname, t.relname, ic.relname;
"""

# Heuristic, not real plan analysis: a query mentioning the index's second
# column but never its leading column can't use this composite index
# efficiently (a B-tree composite index needs the leading column
# constrained to use trailing columns at all) -- but this is a substring
# match on query text, not a parsed predicate list, so it can both miss
# real mismatches (leading column mentioned in a SELECT list, not a WHERE)
# and produce false positives (column name coincidentally substring-matches
# something unrelated). Deliberately capped at Severity.LOW in checks.py.
_QUERIES_MENTIONING_SECOND_COLUMN_NOT_LEADING_SQL = """
    SELECT count(*) AS matched_statement_count
    FROM pg_stat_statements
    WHERE query ILIKE '%%' || %(table_name)s || '%%'
      AND query ILIKE '%%WHERE%%'
      AND query ILIKE '%%' || %(second_column)s || '%%'
      AND query NOT ILIKE '%%' || %(leading_column)s || '%%';
"""


def fetch_unused_indexes(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_UNUSED_INDEXES_SQL)
        return cur.fetchall()


def fetch_unindexed_foreign_keys(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_UNINDEXED_FOREIGN_KEYS_SQL)
        return cur.fetchall()


def fetch_seq_scan_heavy_tables(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _SEQ_SCAN_HEAVY_TABLES_SQL,
            {"min_table_bytes": MIN_TABLE_BYTES_FOR_SEQ_SCAN_CHECK, "min_seq_scan_count": MIN_SEQ_SCAN_COUNT},
        )
        return cur.fetchall()


def fetch_composite_indexes(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_COMPOSITE_INDEXES_SQL)
        return cur.fetchall()


def is_pg_stat_statements_available(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute(_IS_PG_STAT_STATEMENTS_AVAILABLE_SQL)
        return cur.fetchone() is not None


def fetch_queries_mentioning_second_column_not_leading(
    conn: psycopg.Connection, table_name: str, leading_column: str, second_column: str
) -> int:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _QUERIES_MENTIONING_SECOND_COLUMN_NOT_LEADING_SQL,
            {"table_name": table_name, "leading_column": leading_column, "second_column": second_column},
        )
        return cur.fetchone()["matched_statement_count"]


def fetch_jsonb_columns_without_gin(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_JSONB_COLUMNS_WITHOUT_GIN_SQL)
        return cur.fetchall()


def fetch_indexes_sharing_leading_column(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_INDEXES_SHARING_LEADING_COLUMN_SQL)
        return cur.fetchall()


def fetch_high_selectivity_columns_without_index(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _HIGH_SELECTIVITY_COLUMNS_WITHOUT_INDEX_SQL,
            {
                "min_rows": MIN_ROWS_FOR_SELECTIVITY_CHECK,
                "candidate_types": _HIGH_SELECTIVITY_COLUMN_CANDIDATE_TYPES,
            },
        )
        return cur.fetchall()


def fetch_jsonb_columns(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_JSONB_COLUMNS_SQL)
        return cur.fetchall()


def fetch_jsonb_range_query_candidate_count(conn: psycopg.Connection, column_name: str) -> int:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_JSONB_RANGE_QUERY_CANDIDATE_COUNT_SQL, {"column_name": column_name})
        return cur.fetchone()["matched_statement_count"]


def fetch_high_write_tables_with_many_indexes(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _HIGH_WRITE_TABLES_WITH_MANY_INDEXES_SQL,
            {
                "min_write_count": MIN_WRITE_COUNT_FOR_AMPLIFICATION_CHECK,
                "min_index_count": MIN_INDEX_COUNT_FOR_AMPLIFICATION_CONCERN,
            },
        )
        return cur.fetchall()


def fetch_non_partial_indexes_on_flag_columns(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_NON_PARTIAL_INDEXES_ON_FLAG_COLUMNS_SQL, {"flag_column_pattern": FLAG_COLUMN_NAME_PATTERN})
        return cur.fetchall()
