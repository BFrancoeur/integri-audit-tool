"""Category 9 checks are tested against canned row data (no live DB) —
queries.py is what the integration suite validates against real Postgres.
"""

import importlib
from datetime import datetime, timedelta, timezone

from integri_audit_tool.models import Severity

checks = importlib.import_module(
    "integri_audit_tool.categories.09_backup_recovery_and_change_management.checks"
)

_NOW = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)


def test_check_wal_archiving_failures_empty_when_no_failures(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_wal_archiver_status",
        return_value={
            "archived_count": 100,
            "failed_count": 0,
            "last_archived_time": _NOW,
            "last_failed_time": None,
        },
    )
    assert checks.check_wal_archiving_failures(conn=object(), config=None) == []


def test_check_wal_archiving_failures_high_when_actively_failing(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_wal_archiver_status",
        return_value={
            "archived_count": 100,
            "failed_count": 3,
            "last_archived_time": _NOW - timedelta(hours=2),
            "last_failed_time": _NOW,
        },
    )

    findings = checks.check_wal_archiving_failures(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "09.01"
    assert findings[0].severity == Severity.HIGH
    assert "active" in findings[0].title


def test_check_wal_archiving_failures_medium_when_historical_only(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_wal_archiver_status",
        return_value={
            "archived_count": 100,
            "failed_count": 3,
            "last_archived_time": _NOW,
            "last_failed_time": _NOW - timedelta(hours=2),
        },
    )

    findings = checks.check_wal_archiving_failures(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].severity == Severity.MEDIUM
    assert "historical" in findings[0].title


def test_check_wal_archiving_status_summary_always_returns_one_informational_finding(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_wal_archiver_status",
        return_value={
            "archived_count": 0,
            "failed_count": 0,
            "last_archived_time": None,
            "last_failed_time": None,
        },
    )

    findings = checks.check_wal_archiving_status_summary(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "09.02"
    assert findings[0].severity == Severity.INFORMATIONAL
    assert "no wal archiving activity" in findings[0].observation.lower()


def test_check_wal_archiving_status_summary_reports_activity_when_present(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_wal_archiver_status",
        return_value={
            "archived_count": 50,
            "failed_count": 1,
            "last_archived_time": _NOW,
            "last_failed_time": None,
        },
    )

    findings = checks.check_wal_archiving_status_summary(conn=object(), config=None)

    assert len(findings) == 1
    assert "50 archived" in findings[0].observation


def test_check_migration_tracking_table_absent_flags_when_none_found(mocker):
    mocker.patch.object(checks.queries, "fetch_migration_tracking_tables", return_value=[])

    findings = checks.check_migration_tracking_table_absent(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "09.03"
    assert findings[0].severity == Severity.LOW


def test_check_migration_tracking_table_absent_empty_when_found(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_migration_tracking_tables",
        return_value=[{"schema_name": "public", "table_name": "django_migrations"}],
    )
    assert checks.check_migration_tracking_table_absent(conn=object(), config=None) == []


def test_check_replica_topology_absent_flags_when_zero(mocker):
    mocker.patch.object(checks.queries, "fetch_replica_count", return_value=0)

    findings = checks.check_replica_topology_absent(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "09.04"
    assert findings[0].severity == Severity.LOW


def test_check_replica_topology_absent_empty_when_replicas_connected(mocker):
    mocker.patch.object(checks.queries, "fetch_replica_count", return_value=2)
    assert checks.check_replica_topology_absent(conn=object(), config=None) == []
