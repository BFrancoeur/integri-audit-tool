"""Category 5 checks are tested against canned row data (no live DB) —
queries.py is what the integration suite validates against real Postgres.
"""

import importlib
from datetime import timedelta

from integri_audit_tool.models import Severity

checks = importlib.import_module(
    "integri_audit_tool.categories.05_query_patterns_and_application_interaction.checks"
)


def _mock_pg_stat_statements_available(mocker, available: bool):
    mocker.patch.object(checks.queries, "is_pg_stat_statements_available", return_value=available)


def test_check_n_plus_one_candidates_informational_when_unavailable(mocker):
    _mock_pg_stat_statements_available(mocker, False)

    findings = checks.check_n_plus_one_candidates(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "n-plus-one-candidates"
    assert findings[0].severity == Severity.INFORMATIONAL


def test_check_n_plus_one_candidates_builds_finding_per_row(mocker):
    _mock_pg_stat_statements_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_n_plus_one_candidates",
        return_value=[
            {
                "query": "SELECT * FROM orders WHERE customer_id = $1",
                "calls": 5000,
                "rows": 5000,
                "avg_rows_per_call": 1.0,
            }
        ],
    )

    findings = checks.check_n_plus_one_candidates(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "n-plus-one-candidates"
    assert findings[0].severity == Severity.INFORMATIONAL
    assert "5000" in findings[0].title


def test_check_n_plus_one_candidates_empty_when_no_candidates(mocker):
    _mock_pg_stat_statements_available(mocker, True)
    mocker.patch.object(checks.queries, "fetch_n_plus_one_candidates", return_value=[])
    assert checks.check_n_plus_one_candidates(conn=object(), config=None) == []


def test_check_offset_pagination_informational_when_unavailable(mocker):
    _mock_pg_stat_statements_available(mocker, False)

    findings = checks.check_offset_pagination(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "offset-pagination"
    assert findings[0].severity == Severity.INFORMATIONAL


def test_check_offset_pagination_flags_usage(mocker):
    _mock_pg_stat_statements_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_offset_pagination_usage",
        return_value={
            "matched_statement_count": 3,
            "example_queries": ["SELECT * FROM articles ORDER BY id OFFSET $1 LIMIT $2"],
        },
    )

    findings = checks.check_offset_pagination(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "offset-pagination"
    assert findings[0].severity == Severity.LOW
    assert "OFFSET" in findings[0].evidence


def test_check_offset_pagination_empty_when_no_usage(mocker):
    _mock_pg_stat_statements_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_offset_pagination_usage",
        return_value={"matched_statement_count": 0, "example_queries": None},
    )
    assert checks.check_offset_pagination(conn=object(), config=None) == []


def test_check_idle_in_transaction_sessions_flags_medium_for_short_duration(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_idle_in_transaction_sessions",
        return_value=[
            {
                "pid": 123,
                "usename": "app",
                "application_name": "myapp",
                "transaction_duration": timedelta(minutes=1),
                "last_query": "SELECT 1",
            }
        ],
    )

    findings = checks.check_idle_in_transaction_sessions(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "idle-in-transaction-sessions"
    assert findings[0].severity == Severity.MEDIUM
    assert "123" in findings[0].title


def test_check_idle_in_transaction_sessions_flags_high_for_long_duration(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_idle_in_transaction_sessions",
        return_value=[
            {
                "pid": 456,
                "usename": "app",
                "application_name": "myapp",
                "transaction_duration": timedelta(minutes=10),
                "last_query": None,
            }
        ],
    )

    findings = checks.check_idle_in_transaction_sessions(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH
    assert "not visible to this role" in findings[0].observation


def test_check_idle_in_transaction_sessions_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_idle_in_transaction_sessions", return_value=[])
    assert checks.check_idle_in_transaction_sessions(conn=object(), config=None) == []


def test_check_slow_query_monitoring_flags_when_nothing_enabled(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_slow_query_monitoring_status",
        return_value={
            "pg_stat_statements_enabled": False,
            "auto_explain_loaded": False,
            "log_min_duration_statement": "-1",
        },
    )

    findings = checks.check_slow_query_monitoring(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "slow-query-monitoring"
    assert findings[0].severity == Severity.MEDIUM


def test_check_slow_query_monitoring_empty_when_pg_stat_statements_enabled(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_slow_query_monitoring_status",
        return_value={
            "pg_stat_statements_enabled": True,
            "auto_explain_loaded": False,
            "log_min_duration_statement": "-1",
        },
    )
    assert checks.check_slow_query_monitoring(conn=object(), config=None) == []


def test_check_slow_query_monitoring_empty_when_log_min_duration_set(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_slow_query_monitoring_status",
        return_value={
            "pg_stat_statements_enabled": False,
            "auto_explain_loaded": False,
            "log_min_duration_statement": "1000",
        },
    )
    assert checks.check_slow_query_monitoring(conn=object(), config=None) == []
