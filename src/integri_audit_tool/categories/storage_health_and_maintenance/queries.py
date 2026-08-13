"""Raw catalog + statistics SQL for the Storage Health & Maintenance category.

New category (SOP merge, 2026-08-03) consolidating table/index bloat, TOAST
storage, and vacuum/replication-slot root-cause diagnostics — previously
07.04/07.05 lived under scale-and-growth-readiness (see that category's
__init__.py docstring for the move) alongside new content the client SOP
called for.

Where the pgstattuple extension is installed, several checks here prefer a
direct measurement over the heuristic estimate this tool used before it
existed (dead-tuple ratio from pg_stat_user_tables) — checks.py tags each
finding's measurement_method accordingly so a reader can tell a hard number
from an estimate. pgstattuple requires no shared_preload_libraries entry
(unlike pg_stat_statements), so CREATE EXTENSION alone is enough once it's
available on the server.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

MIN_LIVE_ROWS_FOR_STATS = 20
"""Below this row count, dead-tuple ratios are too noisy to be worth flagging."""

BLOAT_INVESTIGATE_THRESHOLD = 0.20
"""Dead-tuple/bloat fraction above which a table or index is worth
investigating -- sourced from the client audit SOP (section A2/A3)."""

BLOAT_REMEDIATE_THRESHOLD = 0.40
"""Dead-tuple/bloat fraction above which remediation (VACUUM/tuning), not
just investigation, is warranted -- sourced from the same SOP. If real
engagements show this pair miscalibrated, the documented fallback is
10%/50% (O'Reilly's "Bad Data Handbook") -- not adopted now, noted here for
future recalibration rather than rediscovered."""

MIN_TOAST_BYTES = 1_000_000
"""TOAST relation size above which out-of-line storage looks like it's
happening at meaningful scale, not just the odd oversized row."""

MIN_ACCESS_COUNT = 10
"""Minimum idx_scan + seq_scan before a table counts as actually being read, not just present."""

INDEX_LARGER_THAN_TABLE_RATIO = 1.0
"""Index-to-table size ratio at which an index being larger than the table
it indexes is flagged -- the SOP calls this out by name as "a red flag worth
a dedicated line item." A pure size comparison, not a bloat measurement."""

LONG_RUNNING_TRANSACTION_THRESHOLD_MINUTES = 30
"""A non-idle transaction open longer than this is worth surfacing as a
possible vacuum-blocking root cause -- long enough to exclude ordinary
short-lived application transactions, short enough to catch a stuck session
before it does real damage to autovacuum's ability to reclaim dead tuples."""

STALLED_REPLICATION_SLOT_RETAINED_BYTES_THRESHOLD = 1_000_000_000
"""WAL retained behind a replication slot above this (1GB) is flagged even
for an active slot, since a slow-but-consuming subscriber can still hold
back the xmin horizon as badly as an abandoned one. An inactive slot is
always flagged regardless of this threshold -- see the query."""

_IS_PGSTATTUPLE_AVAILABLE_SQL = """
    SELECT 1 FROM pg_extension WHERE extname = 'pgstattuple';
"""

# pgstattuple_approx() avoids a full heap scan (unlike pgstattuple()) by using
# free-space-map estimates on larger tables -- appropriate for a read-only
# audit that shouldn't add meaningful I/O load. Percentages come back on a
# 0-100 scale; normalized to a 0-1 ratio here so this and the estimated
# fallback share one threshold convention.
#
# Important nuance confirmed via integration testing: dead_tuple_percent is
# dead *bytes* / total *bytes*, while the estimated fallback below is dead
# *rows* / total *rows* -- related but not identical concepts. On a table
# with meaningful per-tuple/page overhead, a given row-deletion fraction can
# measure noticeably lower here than the row-count-based estimate would
# suggest (e.g. 50% of rows deleted measured as ~18% by this query on a
# small test table). Both are reasonable bloat proxies, but a reader
# shouldn't expect the two paths to report the same number for the same
# underlying change -- only measurement_method (see checks.py) says which
# one produced a given finding.
_TABLE_BLOAT_MEASURED_SQL = """
    SELECT
        n.nspname AS schema_name,
        c.relname AS table_name,
        (s.dead_tuple_percent / 100.0) AS dead_tuple_ratio
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_stat_user_tables t ON t.relid = c.oid
    CROSS JOIN LATERAL pgstattuple_approx(c.oid) s
    WHERE c.relkind = 'r'
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND t.n_live_tup >= %(min_rows)s
      AND (s.dead_tuple_percent / 100.0) >= %(investigate_threshold)s
    ORDER BY dead_tuple_ratio DESC;
"""

# Heuristic fallback when pgstattuple isn't installed -- an estimate from
# planner statistics, not a direct measurement. Moved from
# scale_and_growth_readiness's 07.04 (formerly _HIGH_BLOAT_WITHOUT_TUNING_SQL).
_TABLE_BLOAT_ESTIMATED_SQL = """
    SELECT
        t.schemaname AS schema_name,
        t.relname AS table_name,
        (t.n_dead_tup::numeric / GREATEST(t.n_live_tup, 1)) AS dead_tuple_ratio
    FROM pg_stat_user_tables t
    WHERE t.schemaname NOT IN ('pg_catalog', 'information_schema')
      AND t.n_live_tup >= %(min_rows)s
      AND (t.n_dead_tup::numeric / GREATEST(t.n_live_tup, 1)) >= %(investigate_threshold)s
    ORDER BY dead_tuple_ratio DESC;
"""

# pgstatindex only supports B-tree indexes (am.amname = 'btree') -- GIN/GiST/
# hash have their own stat functions this doesn't attempt to cover. Takes a
# share lock on the index while it runs; bounded by db.py's existing
# lock_timeout, same as every other query in this tool. No non-extension
# fallback is offered for index bloat (unlike table bloat) -- a reliable
# B-tree bloat estimate without pgstattuple is a genuinely hard, fragile
# problem, and an honest "not installed, can't assess" beats a shaky heuristic
# number that might mislead a client.
_INDEX_BLOAT_MEASURED_SQL = """
    SELECT
        n.nspname AS schema_name,
        ic.relname AS index_name,
        tc.relname AS table_name,
        (GREATEST(0, 100 - s.avg_leaf_density) / 100.0) AS estimated_bloat_ratio
    FROM pg_class ic
    JOIN pg_namespace n ON n.oid = ic.relnamespace
    JOIN pg_index i ON i.indexrelid = ic.oid
    JOIN pg_class tc ON tc.oid = i.indrelid
    JOIN pg_am am ON am.oid = ic.relam
    CROSS JOIN LATERAL pgstatindex(ic.oid) s
    WHERE am.amname = 'btree'
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND s.avg_leaf_density IS NOT NULL
      AND (GREATEST(0, 100 - s.avg_leaf_density) / 100.0) >= %(investigate_threshold)s
    ORDER BY estimated_bloat_ratio DESC;
"""

_INDEX_TO_TABLE_SIZE_RATIO_SQL = """
    SELECT
        n.nspname AS schema_name,
        ic.relname AS index_name,
        tc.relname AS table_name,
        pg_relation_size(ic.oid) AS index_bytes,
        pg_relation_size(tc.oid) AS table_bytes
    FROM pg_class ic
    JOIN pg_namespace n ON n.oid = ic.relnamespace
    JOIN pg_index i ON i.indexrelid = ic.oid
    JOIN pg_class tc ON tc.oid = i.indrelid
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND pg_relation_size(tc.oid) > 0
      AND (pg_relation_size(ic.oid)::numeric / pg_relation_size(tc.oid)) >= %(ratio_threshold)s
    ORDER BY (pg_relation_size(ic.oid)::numeric / pg_relation_size(tc.oid)) DESC;
"""

# Measures each table's TOAST relation directly rather than inferring size
# from pg_stats.avg_width -- see the moved-from module's original lesson
# (scale_and_growth_readiness's git history): avg_width shrinks once a value
# is actually TOASTed out-of-line, so it's backwards for exactly the case
# that matters. Widened from JSONB-only to also include large text/bytea
# columns (SOP-sourced; the JSONB-only restriction was this tool's own
# earlier, narrower scope).
_LARGE_TOAST_USAGE_SQL = """
    SELECT
        n.nspname AS schema_name,
        c.relname AS table_name,
        pg_total_relation_size(toast.oid) AS toast_bytes,
        (t.idx_scan + t.seq_scan) AS access_count
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_class toast ON toast.oid = c.reltoastrelid
    JOIN pg_stat_user_tables t ON t.relid = c.oid
    WHERE c.relkind = 'r'
      AND c.reltoastrelid <> 0
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND EXISTS (
          SELECT 1
          FROM information_schema.columns col
          WHERE col.table_schema = n.nspname
            AND col.table_name = c.relname
            AND col.data_type IN ('jsonb', 'text', 'bytea')
      )
      AND pg_total_relation_size(toast.oid) >= %(min_toast_bytes)s
      AND (t.idx_scan + t.seq_scan) >= %(min_access_count)s
    ORDER BY toast_bytes DESC;
"""

# attstorage='x' (EXTENDED: compressed + out-of-line) is Postgres's own
# default for varlena types, so its mere presence isn't a defect -- it's a
# real tradeoff against 'e' (EXTERNAL: out-of-line, uncompressed, cheaper
# partial reads). Only surfaced as context on tables already flagged for
# meaningful TOAST size (reuses MIN_TOAST_BYTES), and always Informational
# in checks.py: this tool can describe the storage mode, not confirm the
# access pattern (frequent partial reads) that would make EXTENDED the wrong
# choice, without pg_stat_statements query-text analysis this check doesn't
# attempt.
_TOAST_STORAGE_STRATEGY_SQL = """
    SELECT
        n.nspname AS schema_name,
        c.relname AS table_name,
        a.attname AS column_name,
        a.attstorage AS storage_mode
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_class toast ON toast.oid = c.reltoastrelid
    JOIN information_schema.columns col
      ON col.table_schema = n.nspname AND col.table_name = c.relname AND col.column_name = a.attname
    WHERE c.relkind = 'r'
      AND c.reltoastrelid <> 0
      AND a.attnum > 0
      AND NOT a.attisdropped
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND col.data_type IN ('jsonb', 'text', 'bytea')
      AND a.attstorage = 'x'
      AND pg_total_relation_size(toast.oid) >= %(min_toast_bytes)s
    ORDER BY n.nspname, c.relname, a.attname;
"""

# unnest() over reloptions rather than a text LIKE match -- reloptions is a
# text[] of "key=value" strings, and this is the exact-match-safe way to
# check one is present, matching how Postgres itself stores autovacuum
# per-table overrides.
_AUTOVACUUM_EXPLICITLY_DISABLED_SQL = """
    SELECT
        n.nspname AS schema_name,
        c.relname AS table_name
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'r'
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND c.reloptions IS NOT NULL
      AND EXISTS (SELECT 1 FROM unnest(c.reloptions) opt WHERE opt = 'autovacuum_enabled=false')
    ORDER BY n.nspname, c.relname;
"""

# Excludes this audit's own connection (pg_backend_pid()) -- otherwise the
# audit's own transaction would eligible to flag itself on a slow run.
_LONG_RUNNING_TRANSACTIONS_SQL = """
    SELECT
        pid,
        usename,
        application_name,
        now() - xact_start AS transaction_duration,
        left(coalesce(query, ''), 200) AS last_query
    FROM pg_stat_activity
    WHERE xact_start IS NOT NULL
      AND state != 'idle'
      AND pid <> pg_backend_pid()
      AND now() - xact_start > (%(threshold_minutes)s * interval '1 minute')
    ORDER BY xact_start ASC;
"""

# An inactive slot (active=false) is flagged unconditionally -- nothing is
# consuming it, so it can hold back the xmin horizon indefinitely with no
# natural recovery. An active slot is only flagged once its retained WAL
# crosses the byte threshold, since a slow-but-consuming subscriber is a
# different (lesser) risk than an abandoned one.
_STALLED_REPLICATION_SLOTS_SQL = """
    SELECT
        slot_name,
        slot_type,
        active,
        pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_bytes
    FROM pg_replication_slots
    WHERE restart_lsn IS NOT NULL
      AND (NOT active OR pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) >= %(retained_bytes_threshold)s)
    ORDER BY retained_bytes DESC NULLS LAST;
"""


def is_pgstattuple_available(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute(_IS_PGSTATTUPLE_AVAILABLE_SQL)
        return cur.fetchone() is not None


def fetch_table_bloat_measured(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _TABLE_BLOAT_MEASURED_SQL,
            {"min_rows": MIN_LIVE_ROWS_FOR_STATS, "investigate_threshold": BLOAT_INVESTIGATE_THRESHOLD},
        )
        return cur.fetchall()


def fetch_table_bloat_estimated(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _TABLE_BLOAT_ESTIMATED_SQL,
            {"min_rows": MIN_LIVE_ROWS_FOR_STATS, "investigate_threshold": BLOAT_INVESTIGATE_THRESHOLD},
        )
        return cur.fetchall()


def fetch_index_bloat_measured(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_INDEX_BLOAT_MEASURED_SQL, {"investigate_threshold": BLOAT_INVESTIGATE_THRESHOLD})
        return cur.fetchall()


def fetch_index_to_table_size_ratio_outliers(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_INDEX_TO_TABLE_SIZE_RATIO_SQL, {"ratio_threshold": INDEX_LARGER_THAN_TABLE_RATIO})
        return cur.fetchall()


def fetch_large_toast_on_hot_tables(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _LARGE_TOAST_USAGE_SQL, {"min_toast_bytes": MIN_TOAST_BYTES, "min_access_count": MIN_ACCESS_COUNT}
        )
        return cur.fetchall()


def fetch_toast_storage_strategy_on_large_columns(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_TOAST_STORAGE_STRATEGY_SQL, {"min_toast_bytes": MIN_TOAST_BYTES})
        return cur.fetchall()


def fetch_autovacuum_explicitly_disabled(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_AUTOVACUUM_EXPLICITLY_DISABLED_SQL)
        return cur.fetchall()


def fetch_long_running_transactions(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _LONG_RUNNING_TRANSACTIONS_SQL,
            {"threshold_minutes": LONG_RUNNING_TRANSACTION_THRESHOLD_MINUTES},
        )
        return cur.fetchall()


def fetch_stalled_replication_slots(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            _STALLED_REPLICATION_SLOTS_SQL,
            {"retained_bytes_threshold": STALLED_REPLICATION_SLOT_RETAINED_BYTES_THRESHOLD},
        )
        return cur.fetchall()
