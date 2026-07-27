"""Integration coverage for category 9's raw SQL against a real Postgres instance.

Unlike tests/unit/categories/test_09_backup_recovery_and_change_management.py
(canned rows), these validate that the SQL in queries.py is actually correct.
Marked `integration`; run explicitly with `pytest -m integration` (requires
Docker).

pg_stat_archiver isn't exercised for actual failures here — that requires a
configured archive_command, out of scope for this test container — only its
shape is validated. Similarly, pg_stat_replication's actual replica-count
behavior requires a second standby instance streaming from this one, out of
scope here; only structural correctness is validated. Table names are
prefixed `c9_` except where testing recognition of specific well-known
migration-tool table names.
"""

import importlib

import pytest

queries = importlib.import_module(
    "integri_audit_tool.categories.backup_recovery_and_change_management.queries"
)

pytestmark = pytest.mark.integration


def test_fetch_wal_archiver_status_returns_expected_shape(pg_conn):
    status = queries.fetch_wal_archiver_status(pg_conn)

    assert isinstance(status["archived_count"], int)
    assert isinstance(status["failed_count"], int)


def test_fetch_migration_tracking_tables_detects_known_table(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE django_migrations (id serial PRIMARY KEY, app text)")

    rows = queries.fetch_migration_tracking_tables(pg_conn)

    assert any(r["table_name"] == "django_migrations" for r in rows)


def test_fetch_migration_tracking_tables_matches_case_insensitively(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute('CREATE TABLE "SequelizeMeta" (name text PRIMARY KEY)')

    rows = queries.fetch_migration_tracking_tables(pg_conn)

    assert any(r["table_name"] == "SequelizeMeta" for r in rows)


def test_fetch_migration_tracking_tables_excludes_unrelated_table(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c9_widgets (id serial PRIMARY KEY)")

    rows = queries.fetch_migration_tracking_tables(pg_conn)

    assert not any(r["table_name"] == "c9_widgets" for r in rows)


def test_fetch_replica_count_returns_non_negative_int(pg_conn):
    count = queries.fetch_replica_count(pg_conn)

    assert isinstance(count, int)
    assert count >= 0
