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


def test_check_never_null_nullable_columns_flags_near_zero_null_frac(mocker):
    """Loosened from strict-zero (SOP-driven, 2026-08-03): a handful of
    legacy nulls shouldn't disqualify an otherwise-required column."""
    mocker.patch.object(
        checks.queries,
        "fetch_nullable_column_null_fractions",
        return_value=[_null_frac_row(null_frac=0.005)],
    )

    findings = checks.check_never_null_nullable_columns(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "never-null-nullable-columns"


def test_check_never_null_nullable_columns_ignores_comfortably_above_threshold(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_nullable_column_null_fractions",
        return_value=[_null_frac_row(null_frac=0.05)],
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


def test_check_low_cardinality_ungoverned_columns_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_low_cardinality_ungoverned_columns",
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

    findings = checks.check_low_cardinality_ungoverned_columns(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "low-cardinality-ungoverned-columns"
    assert findings[0].severity == Severity.MEDIUM
    assert "orders.status" in findings[0].title


def test_check_low_cardinality_ungoverned_columns_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_low_cardinality_ungoverned_columns", return_value=[])
    assert checks.check_low_cardinality_ungoverned_columns(conn=object(), config=None) == []


def test_check_missing_default_on_status_like_columns_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_missing_default_on_status_like_columns",
        return_value=[
            {"schema_name": "public", "table_name": "accounts", "column_name": "is_active", "data_type": "boolean"}
        ],
    )

    findings = checks.check_missing_default_on_status_like_columns(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "missing-default-on-status-like-columns"
    assert findings[0].severity == Severity.LOW
    assert "accounts.is_active" in findings[0].title


def test_check_missing_default_on_status_like_columns_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_missing_default_on_status_like_columns", return_value=[])
    assert checks.check_missing_default_on_status_like_columns(conn=object(), config=None) == []


def test_check_orphaned_rows_on_unvalidated_foreign_keys_flags_confirmed_orphans(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_unvalidated_fk_detail",
        return_value=[
            {
                "conname": "orders_customer_id_fkey",
                "schema_name": "public",
                "table_name": "orders",
                "child_column": "customer_id",
                "parent_schema": "public",
                "parent_table": "customers",
                "parent_column": "id",
            }
        ],
    )
    mocker.patch.object(checks.queries, "fetch_orphaned_child_rows", return_value=[101, 102, 103])
    mocker.patch.object(checks.queries, "ORPHAN_SAMPLE_LIMIT", 20)

    findings = checks.check_orphaned_rows_on_unvalidated_foreign_keys(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "orphaned-rows-on-unvalidated-foreign-keys"
    assert findings[0].severity == Severity.HIGH
    assert "orders.customer_id" in findings[0].title
    assert "3" in findings[0].observation


def test_check_orphaned_rows_on_unvalidated_foreign_keys_says_at_least_when_sample_full(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_unvalidated_fk_detail",
        return_value=[
            {
                "conname": "orders_customer_id_fkey",
                "schema_name": "public",
                "table_name": "orders",
                "child_column": "customer_id",
                "parent_schema": "public",
                "parent_table": "customers",
                "parent_column": "id",
            }
        ],
    )
    mocker.patch.object(checks.queries, "ORPHAN_SAMPLE_LIMIT", 3)
    mocker.patch.object(checks.queries, "fetch_orphaned_child_rows", return_value=[101, 102, 103])

    findings = checks.check_orphaned_rows_on_unvalidated_foreign_keys(conn=object(), config=None)

    assert "at least 3" in findings[0].observation


def test_check_orphaned_rows_on_unvalidated_foreign_keys_skips_fk_with_no_orphans(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_unvalidated_fk_detail",
        return_value=[
            {
                "conname": "orders_customer_id_fkey",
                "schema_name": "public",
                "table_name": "orders",
                "child_column": "customer_id",
                "parent_schema": "public",
                "parent_table": "customers",
                "parent_column": "id",
            }
        ],
    )
    mocker.patch.object(checks.queries, "fetch_orphaned_child_rows", return_value=[])

    findings = checks.check_orphaned_rows_on_unvalidated_foreign_keys(conn=object(), config=None)

    assert findings == []


def test_check_orphaned_rows_on_unvalidated_foreign_keys_empty_when_no_unvalidated_fks(mocker):
    mocker.patch.object(checks.queries, "fetch_unvalidated_fk_detail", return_value=[])
    assert checks.check_orphaned_rows_on_unvalidated_foreign_keys(conn=object(), config=None) == []


_ONE_JSONB_COLUMN = [{"schema_name": "public", "table_name": "products", "column_name": "attributes"}]


def test_check_malformed_jsonb_entries_flags_column_over_threshold(mocker):
    mocker.patch.object(checks.queries, "fetch_jsonb_columns", return_value=_ONE_JSONB_COLUMN)
    mocker.patch.object(
        checks.queries,
        "fetch_empty_jsonb_document_stats",
        return_value={"empty_count": 10, "sample_size": 100},
    )

    findings = checks.check_malformed_jsonb_entries(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "malformed-jsonb-entries"
    assert findings[0].severity == Severity.MEDIUM
    assert "products.attributes" in findings[0].title


def test_check_malformed_jsonb_entries_skips_column_under_threshold(mocker):
    mocker.patch.object(checks.queries, "fetch_jsonb_columns", return_value=_ONE_JSONB_COLUMN)
    mocker.patch.object(
        checks.queries,
        "fetch_empty_jsonb_document_stats",
        return_value={"empty_count": 0, "sample_size": 100},
    )

    findings = checks.check_malformed_jsonb_entries(conn=object(), config=None)

    assert findings == []


def test_check_malformed_jsonb_entries_skips_column_with_small_sample(mocker):
    mocker.patch.object(checks.queries, "fetch_jsonb_columns", return_value=_ONE_JSONB_COLUMN)
    mocker.patch.object(
        checks.queries,
        "fetch_empty_jsonb_document_stats",
        return_value={"empty_count": 1, "sample_size": 5},
    )

    findings = checks.check_malformed_jsonb_entries(conn=object(), config=None)

    assert findings == []


def test_check_malformed_jsonb_entries_empty_when_no_jsonb_columns(mocker):
    mocker.patch.object(checks.queries, "fetch_jsonb_columns", return_value=[])
    assert checks.check_malformed_jsonb_entries(conn=object(), config=None) == []
