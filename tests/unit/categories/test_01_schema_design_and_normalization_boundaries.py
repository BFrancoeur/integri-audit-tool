"""Category 1 checks are tested against canned row data (no live DB) —
queries.py is what the integration suite validates against real Postgres.
"""

import importlib

from integri_audit_tool.models import Severity

checks = importlib.import_module(
    "integri_audit_tool.categories.01_schema_design_and_normalization_boundaries.checks"
)


def test_check_missing_foreign_keys_flags_unconstrained_fk_shaped_column(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_fk_like_columns_without_fk",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "orders",
                "column_name": "customer_id",
                "data_type": "integer",
            }
        ],
    )

    findings = checks.check_missing_foreign_keys(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "missing-foreign-keys"
    assert findings[0].severity == Severity.MEDIUM
    assert "orders.customer_id" in findings[0].title


def test_check_missing_foreign_keys_returns_empty_when_no_rows(mocker):
    mocker.patch.object(checks.queries, "fetch_fk_like_columns_without_fk", return_value=[])
    assert checks.check_missing_foreign_keys(conn=object(), config=None) == []


def test_check_schema_drift_flags_type_mismatch_as_medium(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_columns_with_name_or_type_drift",
        return_value=[
            {
                "normalized_name": "createdat",
                "observed_names": ["created_at", "createdAt"],
                "observed_types": ["timestamp with time zone", "text"],
                "tables": ["table_a", "table_b"],
            }
        ],
    )

    findings = checks.check_schema_drift(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "schema-drift"
    assert findings[0].severity == Severity.MEDIUM
    assert "naming and type" in findings[0].title


def test_check_schema_drift_flags_naming_only_as_low(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_columns_with_name_or_type_drift",
        return_value=[
            {
                "normalized_name": "email",
                "observed_names": ["email", "Email"],
                "observed_types": ["text"],
                "tables": ["table_a", "table_b"],
            }
        ],
    )

    findings = checks.check_schema_drift(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].severity == Severity.LOW
    assert "naming)" in findings[0].title


def test_check_primary_key_consistency_flags_table_without_pk(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_tables_without_primary_key",
        return_value=[{"schema_name": "public", "table_name": "logs"}],
    )
    mocker.patch.object(checks.queries, "fetch_primary_key_column_types", return_value=[])

    findings = checks.check_primary_key_consistency(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "primary-key-consistency"
    assert findings[0].severity == Severity.HIGH
    assert "logs" in findings[0].title


def test_check_primary_key_consistency_flags_mixed_pk_type_families(mocker):
    mocker.patch.object(checks.queries, "fetch_tables_without_primary_key", return_value=[])
    mocker.patch.object(
        checks.queries,
        "fetch_primary_key_column_types",
        return_value=[
            {"schema_name": "public", "table_name": "customers", "data_type": "uuid"},
            {"schema_name": "public", "table_name": "orders", "data_type": "integer"},
        ],
    )

    findings = checks.check_primary_key_consistency(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].severity == Severity.INFORMATIONAL
    assert "Mixed primary key type families" in findings[0].title


def test_check_primary_key_consistency_no_findings_when_all_consistent(mocker):
    mocker.patch.object(checks.queries, "fetch_tables_without_primary_key", return_value=[])
    mocker.patch.object(
        checks.queries,
        "fetch_primary_key_column_types",
        return_value=[
            {"schema_name": "public", "table_name": "customers", "data_type": "integer"},
            {"schema_name": "public", "table_name": "orders", "data_type": "bigint"},
        ],
    )

    findings = checks.check_primary_key_consistency(conn=object(), config=None)

    assert findings == []
