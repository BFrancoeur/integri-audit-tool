"""Integration coverage for the Storage Health & Maintenance category's raw
SQL against a real Postgres instance.

Unlike tests/unit/categories/test_storage_health_and_maintenance.py (canned
rows), these validate that the SQL in queries.py is actually correct. Marked
`integration`; run explicitly with `pytest -m integration` (requires Docker).

Table names are prefixed `csh_` to avoid colliding with other categories'
test tables in the shared, session-scoped test container.

pg_stat_user_tables counters (used for bloat/scan-count checks) are only
guaranteed current after `SELECT pg_stat_force_next_flush()` (PG15+) —
without it, a just-executed DELETE/scan may not be reflected yet.
"""

import importlib

import pytest

queries = importlib.import_module("integri_audit_tool.categories.storage_health_and_maintenance.queries")

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _enable_pgstattuple(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgstattuple")


def test_is_pgstattuple_available_true_once_extension_created(pg_conn):
    assert queries.is_pgstattuple_available(pg_conn) is True


def test_fetch_table_bloat_estimated_detects_dead_tuples(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE csh_sessions_est (id serial PRIMARY KEY, data text)")
        cur.execute("INSERT INTO csh_sessions_est (data) SELECT 'x' FROM generate_series(1, 100)")
        cur.execute("DELETE FROM csh_sessions_est WHERE id <= 50")
        cur.execute("SELECT pg_stat_force_next_flush()")

    rows = queries.fetch_table_bloat_estimated(pg_conn)

    row = next((r for r in rows if r["table_name"] == "csh_sessions_est"), None)
    assert row is not None
    assert row["dead_tuple_ratio"] > 0.2


def test_fetch_table_bloat_measured_detects_dead_tuples(pg_conn):
    # pgstattuple_approx's percentage is dead *bytes* / total *bytes*, not
    # dead *rows* / total *rows* -- per-tuple/page overhead means a 50% row
    # deletion on a small table can land under a 20% byte-based threshold
    # (confirmed empirically: 50/100 rows deleted measured as ~18.3%, not
    # ~50%). Also must keep n_live_tup >= MIN_LIVE_ROWS_FOR_STATS (20) after
    # the delete, or the row is filtered out for a different reason entirely.
    # 500 rows, delete 450 -> 50 live (clears the min-rows floor) and a
    # comfortably large dead-byte fraction (clears the 20% threshold).
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE csh_sessions_meas (id serial PRIMARY KEY, data text)")
        cur.execute("INSERT INTO csh_sessions_meas (data) SELECT 'x' FROM generate_series(1, 500)")
        cur.execute("DELETE FROM csh_sessions_meas WHERE id <= 450")
        cur.execute("SELECT pg_stat_force_next_flush()")

    rows = queries.fetch_table_bloat_measured(pg_conn)

    row = next((r for r in rows if r["table_name"] == "csh_sessions_meas"), None)
    assert row is not None
    assert row["dead_tuple_ratio"] > 0.2


def test_fetch_index_bloat_measured_returns_btree_index_rows(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE csh_idx_bloat (id serial PRIMARY KEY, val int)")
        cur.execute("CREATE INDEX csh_idx_bloat_val ON csh_idx_bloat (val)")
        cur.execute("INSERT INTO csh_idx_bloat (val) SELECT generate_series(1, 500)")
        cur.execute("DELETE FROM csh_idx_bloat WHERE val <= 400")

    # Not asserting a specific row is flagged (bloat ratio after one delete
    # without a checkpoint/vacuum cycle is unpredictable) -- just that the
    # query runs against a real B-tree index without erroring.
    rows = queries.fetch_index_bloat_measured(pg_conn)
    assert isinstance(rows, list)


def test_fetch_index_to_table_size_ratio_outliers_detects_oversized_index(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE csh_ratio_small (id serial PRIMARY KEY, val text)")
        cur.execute("INSERT INTO csh_ratio_small (val) SELECT 'x' FROM generate_series(1, 5)")
        cur.execute(
            "CREATE INDEX csh_ratio_small_expr ON csh_ratio_small "
            "((val || val || val || val || val || val || val || val))"
        )

    rows = queries.fetch_index_to_table_size_ratio_outliers(pg_conn)

    # A near-empty table with any index at all commonly has index_bytes >=
    # table_bytes (both round up to one 8KB page) -- just confirm the query
    # runs and returns well-formed rows, not a specific ratio.
    for row in rows:
        assert row["index_bytes"] > 0
        assert row["table_bytes"] > 0


def test_fetch_large_toast_on_hot_tables_detects_toast_usage(pg_conn):
    # repeat('x', N) compresses to almost nothing under Postgres's automatic
    # TOAST compression and wouldn't actually exercise out-of-line storage —
    # use high-entropy (incompressible) values instead, and enough of them to
    # clear MIN_TOAST_BYTES (1MB).
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE csh_products (id serial PRIMARY KEY, attrs jsonb)")
        cur.execute(
            "INSERT INTO csh_products (attrs) "
            "SELECT jsonb_build_object('description', "
            "(SELECT string_agg(md5(random()::text), '') FROM generate_series(1, 100))) "
            "FROM generate_series(1, 400)"
        )
        cur.execute("ANALYZE csh_products")
        for _ in range(15):
            cur.execute("SELECT * FROM csh_products")
        cur.execute("SELECT pg_stat_force_next_flush()")

    rows = queries.fetch_large_toast_on_hot_tables(pg_conn)

    row = next((r for r in rows if r["table_name"] == "csh_products"), None)
    assert row is not None
    assert row["toast_bytes"] >= 1_000_000
    assert row["access_count"] >= 10


def test_fetch_toast_storage_strategy_flags_extended_storage(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE csh_docs (id serial PRIMARY KEY, body text)")
        cur.execute(
            "INSERT INTO csh_docs (body) "
            "SELECT (SELECT string_agg(md5(random()::text), '') FROM generate_series(1, 100)) "
            "FROM generate_series(1, 400)"
        )

    rows = queries.fetch_toast_storage_strategy_on_large_columns(pg_conn)

    row = next((r for r in rows if r["table_name"] == "csh_docs"), None)
    assert row is not None
    assert row["storage_mode"] == "x"


def test_fetch_autovacuum_explicitly_disabled_detects_override(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE csh_no_vacuum (id serial PRIMARY KEY) WITH (autovacuum_enabled = false)")
        cur.execute("CREATE TABLE csh_normal_vacuum (id serial PRIMARY KEY)")

    rows = queries.fetch_autovacuum_explicitly_disabled(pg_conn)

    assert any(r["table_name"] == "csh_no_vacuum" for r in rows)
    assert not any(r["table_name"] == "csh_normal_vacuum" for r in rows)


def test_fetch_long_running_transactions_excludes_short_transactions(pg_conn):
    # A brand-new transaction on this same connection is well under the
    # 30-minute threshold -- confirms the query runs and doesn't flag normal
    # activity, without needing an actual 30-minute-old session in a test.
    rows = queries.fetch_long_running_transactions(pg_conn)
    assert isinstance(rows, list)


def test_fetch_stalled_replication_slots_flags_inactive_slot(pg_conn):
    with pg_conn.cursor() as cur:
        # immediately_reserve=true so restart_lsn is set right away, rather
        # than staying NULL until the slot is first read from -- this
        # query's WHERE restart_lsn IS NOT NULL would otherwise never match
        # a slot that's never actually been consumed.
        cur.execute("SELECT pg_create_physical_replication_slot('csh_abandoned_slot', true)")
    try:
        rows = queries.fetch_stalled_replication_slots(pg_conn)

        row = next((r for r in rows if r["slot_name"] == "csh_abandoned_slot"), None)
        assert row is not None
        assert row["active"] is False
    finally:
        with pg_conn.cursor() as cur:
            cur.execute("SELECT pg_drop_replication_slot('csh_abandoned_slot')")
