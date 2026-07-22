"""Category 7 checks are tested against canned row data (no live DB) —
queries.py is what the integration suite validates against real Postgres.
"""

import importlib

from integri_audit_tool.models import Severity

checks = importlib.import_module("integri_audit_tool.categories.07_scale_and_growth_readiness.checks")


def _mock_pg_stat_statements_available(mocker, available: bool):
    mocker.patch.object(checks.queries, "is_pg_stat_statements_available", return_value=available)


def test_check_slow_queries_informational_when_unavailable(mocker):
    _mock_pg_stat_statements_available(mocker, False)

    findings = checks.check_slow_queries(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "07.01"
    assert findings[0].severity == Severity.INFORMATIONAL


def test_check_slow_queries_flags_medium_below_high_threshold(mocker):
    _mock_pg_stat_statements_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_slow_queries",
        return_value=[
            {"query": "SELECT * FROM big_table", "calls": 10, "mean_exec_time": 1500.0, "max_exec_time": 2000.0}
        ],
    )

    findings = checks.check_slow_queries(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "07.01"
    assert findings[0].severity == Severity.MEDIUM


def test_check_slow_queries_flags_high_above_threshold(mocker):
    _mock_pg_stat_statements_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_slow_queries",
        return_value=[
            {"query": "SELECT * FROM huge_table", "calls": 10, "mean_exec_time": 6000.0, "max_exec_time": 9000.0}
        ],
    )

    findings = checks.check_slow_queries(conn=object(), config=None)

    assert findings[0].severity == Severity.HIGH


def test_check_slow_queries_empty_when_no_rows(mocker):
    _mock_pg_stat_statements_available(mocker, True)
    mocker.patch.object(checks.queries, "fetch_slow_queries", return_value=[])
    assert checks.check_slow_queries(conn=object(), config=None) == []


def test_check_largest_tables_builds_single_informational_finding(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_largest_tables",
        return_value=[
            {"schema_name": "public", "table_name": "orders", "total_bytes": 5_000_000_000},
            {"schema_name": "public", "table_name": "logs", "total_bytes": 1_000_000},
        ],
    )

    findings = checks.check_largest_tables(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "07.02"
    assert findings[0].severity == Severity.INFORMATIONAL
    assert "orders" in findings[0].observation
    assert "GB" in findings[0].observation


def test_check_largest_tables_empty_when_no_tables(mocker):
    mocker.patch.object(checks.queries, "fetch_largest_tables", return_value=[])
    assert checks.check_largest_tables(conn=object(), config=None) == []


def test_check_tenant_columns_without_rls_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_tenant_columns_without_rls",
        return_value=[{"schema_name": "public", "table_name": "invoices"}],
    )

    findings = checks.check_tenant_columns_without_rls(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "07.03"
    assert findings[0].severity == Severity.MEDIUM
    assert "invoices" in findings[0].title


def test_check_tenant_columns_without_rls_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_tenant_columns_without_rls", return_value=[])
    assert checks.check_tenant_columns_without_rls(conn=object(), config=None) == []


def test_check_high_bloat_tables_flags_medium_below_high_threshold(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_high_bloat_tables_without_tuning",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "sessions",
                "n_live_tup": 1000,
                "n_dead_tup": 300,
                "dead_tuple_ratio": 0.3,
            }
        ],
    )

    findings = checks.check_high_bloat_tables_without_tuning(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "07.04"
    assert findings[0].severity == Severity.MEDIUM


def test_check_high_bloat_tables_flags_high_above_threshold(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_high_bloat_tables_without_tuning",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "sessions",
                "n_live_tup": 1000,
                "n_dead_tup": 600,
                "dead_tuple_ratio": 0.6,
            }
        ],
    )

    findings = checks.check_high_bloat_tables_without_tuning(conn=object(), config=None)

    assert findings[0].severity == Severity.HIGH


def test_check_high_bloat_tables_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_high_bloat_tables_without_tuning", return_value=[])
    assert checks.check_high_bloat_tables_without_tuning(conn=object(), config=None) == []


def test_check_large_jsonb_on_hot_tables_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_large_jsonb_on_hot_tables",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "products",
                "toast_bytes": 5_000_000,
                "access_count": 500,
            }
        ],
    )

    findings = checks.check_large_jsonb_on_hot_tables(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "07.05"
    assert findings[0].severity == Severity.MEDIUM
    assert "products" in findings[0].title


def test_check_large_jsonb_on_hot_tables_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_large_jsonb_on_hot_tables", return_value=[])
    assert checks.check_large_jsonb_on_hot_tables(conn=object(), config=None) == []
