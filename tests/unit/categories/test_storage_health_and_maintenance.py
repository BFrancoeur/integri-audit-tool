"""Storage Health & Maintenance checks are tested against canned row data
(no live DB) — queries.py is what the integration suite validates against
real Postgres.
"""

import importlib

from integri_audit_tool.models import Severity

checks = importlib.import_module("integri_audit_tool.categories.storage_health_and_maintenance.checks")


def _mock_pgstattuple_available(mocker, available: bool):
    mocker.patch.object(checks.queries, "is_pgstattuple_available", return_value=available)


def test_check_table_bloat_uses_measured_path_when_pgstattuple_available(mocker):
    _mock_pgstattuple_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_table_bloat_measured",
        return_value=[{"schema_name": "public", "table_name": "sessions", "dead_tuple_ratio": 0.25}],
    )
    mocker.patch.object(checks.queries, "fetch_table_bloat_estimated", return_value=[])

    findings = checks.check_table_bloat(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "table-bloat"
    assert findings[0].measurement_method == "measured"
    assert findings[0].severity == Severity.MEDIUM


def test_check_table_bloat_falls_back_to_estimated_when_pgstattuple_unavailable(mocker):
    _mock_pgstattuple_available(mocker, False)
    mocker.patch.object(
        checks.queries,
        "fetch_table_bloat_estimated",
        return_value=[{"schema_name": "public", "table_name": "sessions", "dead_tuple_ratio": 0.5}],
    )

    findings = checks.check_table_bloat(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].measurement_method == "estimated"
    assert findings[0].severity == Severity.HIGH


def test_check_table_bloat_severity_split_at_remediate_threshold(mocker):
    _mock_pgstattuple_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_table_bloat_measured",
        return_value=[
            {"schema_name": "public", "table_name": "just_below", "dead_tuple_ratio": 0.39},
            {"schema_name": "public", "table_name": "at_threshold", "dead_tuple_ratio": 0.40},
        ],
    )

    findings = checks.check_table_bloat(conn=object(), config=None)

    by_table = {f.title.split(": ")[1].split(" (")[0]: f for f in findings}
    assert by_table["just_below"].severity == Severity.MEDIUM
    assert by_table["at_threshold"].severity == Severity.HIGH


def test_check_table_bloat_empty_when_no_rows(mocker):
    _mock_pgstattuple_available(mocker, True)
    mocker.patch.object(checks.queries, "fetch_table_bloat_measured", return_value=[])
    assert checks.check_table_bloat(conn=object(), config=None) == []


def test_check_index_bloat_informational_when_pgstattuple_unavailable(mocker):
    _mock_pgstattuple_available(mocker, False)

    findings = checks.check_index_bloat(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "index-bloat"
    assert findings[0].severity == Severity.INFORMATIONAL
    assert findings[0].measurement_method is None


def test_check_index_bloat_flags_measured_rows(mocker):
    _mock_pgstattuple_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_index_bloat_measured",
        return_value=[
            {
                "schema_name": "public",
                "index_name": "idx_orders_customer",
                "table_name": "orders",
                "estimated_bloat_ratio": 0.45,
            }
        ],
    )

    findings = checks.check_index_bloat(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].measurement_method == "measured"
    assert findings[0].severity == Severity.HIGH
    assert "idx_orders_customer" in findings[0].title


def test_check_index_bloat_empty_when_no_rows(mocker):
    _mock_pgstattuple_available(mocker, True)
    mocker.patch.object(checks.queries, "fetch_index_bloat_measured", return_value=[])
    assert checks.check_index_bloat(conn=object(), config=None) == []


def test_check_index_to_table_size_ratio_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_index_to_table_size_ratio_outliers",
        return_value=[
            {
                "schema_name": "public",
                "index_name": "idx_big",
                "table_name": "small_table",
                "index_bytes": 200_000_000,
                "table_bytes": 100_000_000,
            }
        ],
    )

    findings = checks.check_index_to_table_size_ratio(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "index-to-table-size-ratio"
    assert findings[0].severity == Severity.LOW
    assert "idx_big" in findings[0].title


def test_check_index_to_table_size_ratio_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_index_to_table_size_ratio_outliers", return_value=[])
    assert checks.check_index_to_table_size_ratio(conn=object(), config=None) == []


def test_check_large_toast_on_hot_tables_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_large_toast_on_hot_tables",
        return_value=[
            {"schema_name": "public", "table_name": "products", "toast_bytes": 5_000_000, "access_count": 500}
        ],
    )

    findings = checks.check_large_toast_on_hot_tables(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "large-toast-on-hot-tables"
    assert findings[0].severity == Severity.MEDIUM
    assert "products" in findings[0].title


def test_check_large_toast_on_hot_tables_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_large_toast_on_hot_tables", return_value=[])
    assert checks.check_large_toast_on_hot_tables(conn=object(), config=None) == []


def test_check_toast_storage_strategy_is_always_informational(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_toast_storage_strategy_on_large_columns",
        return_value=[
            {"schema_name": "public", "table_name": "products", "column_name": "attrs", "storage_mode": "x"}
        ],
    )

    findings = checks.check_toast_storage_strategy(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].severity == Severity.INFORMATIONAL
    assert "attrs" in findings[0].title


def test_check_toast_storage_strategy_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_toast_storage_strategy_on_large_columns", return_value=[])
    assert checks.check_toast_storage_strategy(conn=object(), config=None) == []


def test_check_autovacuum_explicitly_disabled_flags_high_severity(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_autovacuum_explicitly_disabled",
        return_value=[{"schema_name": "public", "table_name": "logs"}],
    )

    findings = checks.check_autovacuum_explicitly_disabled(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH
    assert "logs" in findings[0].title


def test_check_autovacuum_explicitly_disabled_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_autovacuum_explicitly_disabled", return_value=[])
    assert checks.check_autovacuum_explicitly_disabled(conn=object(), config=None) == []


def test_check_xmin_horizon_risk_flags_long_running_transaction(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_long_running_transactions",
        return_value=[
            {
                "pid": 1234,
                "usename": "app_user",
                "application_name": "batch_job",
                "transaction_duration": "00:45:00",
                "last_query": "UPDATE big_table SET ...",
            }
        ],
    )
    mocker.patch.object(checks.queries, "fetch_stalled_replication_slots", return_value=[])

    findings = checks.check_xmin_horizon_risk(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "xmin-horizon-risk"
    assert findings[0].severity == Severity.HIGH
    assert "1234" in findings[0].title


def test_check_xmin_horizon_risk_flags_stalled_replication_slot(mocker):
    mocker.patch.object(checks.queries, "fetch_long_running_transactions", return_value=[])
    mocker.patch.object(
        checks.queries,
        "fetch_stalled_replication_slots",
        return_value=[{"slot_name": "abandoned_slot", "slot_type": "physical", "active": False, "retained_bytes": None}],
    )

    findings = checks.check_xmin_horizon_risk(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH
    assert "abandoned_slot" in findings[0].title
    assert "inactive" in findings[0].observation


def test_check_xmin_horizon_risk_combines_both_sources(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_long_running_transactions",
        return_value=[
            {
                "pid": 1,
                "usename": "a",
                "application_name": "b",
                "transaction_duration": "01:00:00",
                "last_query": "q",
            }
        ],
    )
    mocker.patch.object(
        checks.queries,
        "fetch_stalled_replication_slots",
        return_value=[{"slot_name": "slot_a", "slot_type": "physical", "active": True, "retained_bytes": 2_000_000_000}],
    )

    findings = checks.check_xmin_horizon_risk(conn=object(), config=None)

    assert len(findings) == 2
    assert all(f.check_slug == "xmin-horizon-risk" for f in findings)


def test_check_xmin_horizon_risk_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_long_running_transactions", return_value=[])
    mocker.patch.object(checks.queries, "fetch_stalled_replication_slots", return_value=[])
    assert checks.check_xmin_horizon_risk(conn=object(), config=None) == []
