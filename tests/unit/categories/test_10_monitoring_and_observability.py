"""Category 10 checks are tested against canned row data (no live DB) —
queries.py is what the integration suite validates against real Postgres.
"""

import importlib
from datetime import datetime, timedelta, timezone

from integri_audit_tool.models import Severity

checks = importlib.import_module("integri_audit_tool.categories.10_monitoring_and_observability.checks")

_NOW = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)


def test_check_pg_stat_statements_installed_flags_when_missing(mocker):
    mocker.patch.object(checks.queries, "is_pg_stat_statements_available", return_value=False)

    findings = checks.check_pg_stat_statements_installed(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "pg-stat-statements-installed"
    assert findings[0].severity == Severity.MEDIUM


def test_check_pg_stat_statements_installed_empty_when_present(mocker):
    mocker.patch.object(checks.queries, "is_pg_stat_statements_available", return_value=True)
    assert checks.check_pg_stat_statements_installed(conn=object(), config=None) == []


def _mock_no_long_running_queries(mocker):
    mocker.patch.object(checks.queries, "fetch_long_running_active_queries", return_value=[])


def test_check_connection_saturation_flags_high_usage(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_connection_saturation",
        return_value={"current_connections": 85, "max_connections": 100},
    )
    _mock_no_long_running_queries(mocker)

    findings = checks.check_connection_saturation(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "connection-saturation"
    assert findings[0].severity == Severity.HIGH
    assert "85%" in findings[0].title


def test_check_connection_saturation_empty_when_usage_low(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_connection_saturation",
        return_value={"current_connections": 10, "max_connections": 100},
    )
    _mock_no_long_running_queries(mocker)

    assert checks.check_connection_saturation(conn=object(), config=None) == []


def test_check_connection_saturation_flags_medium_for_long_running_query(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_connection_saturation",
        return_value={"current_connections": 10, "max_connections": 100},
    )
    mocker.patch.object(
        checks.queries,
        "fetch_long_running_active_queries",
        return_value=[
            {
                "pid": 111,
                "usename": "app",
                "application_name": "myapp",
                "query_duration": timedelta(minutes=6),
                "query": "SELECT * FROM big_table",
            }
        ],
    )

    findings = checks.check_connection_saturation(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "connection-saturation"
    assert findings[0].severity == Severity.MEDIUM
    assert "111" in findings[0].title


def test_check_connection_saturation_flags_high_for_very_long_running_query(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_connection_saturation",
        return_value={"current_connections": 10, "max_connections": 100},
    )
    mocker.patch.object(
        checks.queries,
        "fetch_long_running_active_queries",
        return_value=[
            {
                "pid": 222,
                "usename": "app",
                "application_name": "myapp",
                "query_duration": timedelta(minutes=20),
                "query": None,
            }
        ],
    )

    findings = checks.check_connection_saturation(conn=object(), config=None)

    assert findings[0].severity == Severity.HIGH
    assert "not visible to this role" in findings[0].observation


def test_check_connection_saturation_combines_both_subchecks(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_connection_saturation",
        return_value={"current_connections": 90, "max_connections": 100},
    )
    mocker.patch.object(
        checks.queries,
        "fetch_long_running_active_queries",
        return_value=[
            {
                "pid": 333,
                "usename": "app",
                "application_name": "myapp",
                "query_duration": timedelta(minutes=6),
                "query": "SELECT 1",
            }
        ],
    )

    findings = checks.check_connection_saturation(conn=object(), config=None)

    assert len(findings) == 2
    assert {f.check_slug for f in findings} == {"connection-saturation"}


def test_check_bloated_tables_without_recent_vacuum_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_bloated_tables_without_recent_vacuum",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "sessions",
                "n_live_tup": 1000,
                "n_dead_tup": 500,
                "dead_tuple_ratio": 0.5,
                "last_vacuum": None,
                "last_autovacuum": _NOW - timedelta(days=30),
            }
        ],
    )

    findings = checks.check_bloated_tables_without_recent_vacuum(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "bloated-tables-without-recent-vacuum"
    assert findings[0].severity == Severity.MEDIUM
    assert "sessions" in findings[0].title


def test_check_bloated_tables_without_recent_vacuum_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_bloated_tables_without_recent_vacuum", return_value=[])
    assert checks.check_bloated_tables_without_recent_vacuum(conn=object(), config=None) == []
