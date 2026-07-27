"""Category 6 checks are tested against canned row data (no live DB) —
queries.py is what the integration suite validates against real Postgres.
"""

import importlib

from integri_audit_tool.models import Severity

checks = importlib.import_module("integri_audit_tool.categories.data_quality_and_integrity.checks")


def _null_frac_row(**overrides):
    row = {
        "schema_name": "public",
        "table_name": "orders",
        "column_name": "notes",
        "null_frac": 0.0,
        "n_live_tup": 1000,
    }
    row.update(overrides)
    return row


def test_check_high_null_fraction_columns_flags_above_threshold(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_nullable_column_null_fractions",
        return_value=[_null_frac_row(null_frac=0.75)],
    )

    findings = checks.check_high_null_fraction_columns(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "high-null-fraction-columns"
    assert findings[0].severity == Severity.INFORMATIONAL
    assert "75%" in findings[0].title


def test_check_high_null_fraction_columns_ignores_below_threshold(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_nullable_column_null_fractions",
        return_value=[_null_frac_row(null_frac=0.2)],
    )
    assert checks.check_high_null_fraction_columns(conn=object(), config=None) == []


def test_check_unvalidated_foreign_keys_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_unvalidated_foreign_keys",
        return_value=[
            {
                "conname": "orders_customer_id_fkey",
                "schema_name": "public",
                "table_name": "orders",
                "constraint_def": "FOREIGN KEY (customer_id) REFERENCES customers(id)",
            }
        ],
    )

    findings = checks.check_unvalidated_foreign_keys(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "unvalidated-foreign-keys"
    assert findings[0].severity == Severity.MEDIUM
    assert "orders_customer_id_fkey" in findings[0].title


def test_check_unvalidated_foreign_keys_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_unvalidated_foreign_keys", return_value=[])
    assert checks.check_unvalidated_foreign_keys(conn=object(), config=None) == []


def test_check_near_unique_columns_flags_high_ratio_via_negative_n_distinct(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_columns_without_unique_constraint",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "customers",
                "column_name": "email",
                "n_distinct": -1.0,
                "n_live_tup": 1000,
            }
        ],
    )

    findings = checks.check_near_unique_columns_without_constraint(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "near-unique-columns-without-constraint"
    assert findings[0].severity == Severity.MEDIUM
    assert "100%" in findings[0].observation


def test_check_near_unique_columns_flags_high_ratio_via_positive_n_distinct(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_columns_without_unique_constraint",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "customers",
                "column_name": "email",
                "n_distinct": 990,
                "n_live_tup": 1000,
            }
        ],
    )

    findings = checks.check_near_unique_columns_without_constraint(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "near-unique-columns-without-constraint"


def test_check_near_unique_columns_ignores_low_ratio(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_columns_without_unique_constraint",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "orders",
                "column_name": "status",
                "n_distinct": 5,
                "n_live_tup": 1000,
            }
        ],
    )
    assert checks.check_near_unique_columns_without_constraint(conn=object(), config=None) == []


def test_check_never_null_nullable_columns_flags_zero_null_frac(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_nullable_column_null_fractions",
        return_value=[_null_frac_row(null_frac=0.0)],
    )

    findings = checks.check_never_null_nullable_columns(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "never-null-nullable-columns"
    assert findings[0].severity == Severity.LOW


def test_check_never_null_nullable_columns_ignores_nonzero(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_nullable_column_null_fractions",
        return_value=[_null_frac_row(null_frac=0.01)],
    )
    assert checks.check_never_null_nullable_columns(conn=object(), config=None) == []


def test_check_audit_timestamp_columns_have_nulls_builds_finding(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_audit_timestamp_column_null_fractions",
        return_value=[_null_frac_row(column_name="updated_at", null_frac=0.3)],
    )

    findings = checks.check_audit_timestamp_columns_have_nulls(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "audit-timestamp-columns-have-nulls"
    assert findings[0].severity == Severity.MEDIUM
    assert "updated_at" in findings[0].title


def test_check_audit_timestamp_columns_have_nulls_empty_when_no_rows(mocker):
    mocker.patch.object(checks.queries, "fetch_audit_timestamp_column_null_fractions", return_value=[])
    assert checks.check_audit_timestamp_columns_have_nulls(conn=object(), config=None) == []
