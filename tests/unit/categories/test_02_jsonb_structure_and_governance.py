"""Category 2 checks are tested against canned row data (no live DB) —
queries.py is what the integration suite validates against real Postgres.
"""

import importlib

from integri_audit_tool.models import Severity

checks = importlib.import_module("integri_audit_tool.categories.02_jsonb_structure_and_governance.checks")

_ONE_COLUMN = [{"schema_name": "public", "table_name": "products", "column_name": "attrs"}]


def test_is_applicable_true_when_jsonb_columns_exist(mocker):
    mocker.patch.object(checks.queries, "fetch_jsonb_columns", return_value=_ONE_COLUMN)
    assert checks.is_applicable(conn=object()) is True


def test_is_applicable_false_when_no_jsonb_columns(mocker):
    mocker.patch.object(checks.queries, "fetch_jsonb_columns", return_value=[])
    assert checks.is_applicable(conn=object()) is False


def test_check_key_naming_drift_builds_finding_per_variant_group(mocker):
    mocker.patch.object(checks.queries, "fetch_jsonb_columns", return_value=_ONE_COLUMN)
    mocker.patch.object(
        checks.queries,
        "fetch_key_naming_variants",
        return_value=[
            {"normalized_key": "diameterin", "observed_keys": ["diameter_in", "diameterIn"]}
        ],
    )

    findings = checks.check_key_naming_drift(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "02.02"
    assert findings[0].severity == Severity.LOW
    assert "diameterin" in findings[0].title


def test_check_key_naming_drift_returns_empty_when_no_variants(mocker):
    mocker.patch.object(checks.queries, "fetch_jsonb_columns", return_value=_ONE_COLUMN)
    mocker.patch.object(checks.queries, "fetch_key_naming_variants", return_value=[])
    assert checks.check_key_naming_drift(conn=object(), config=None) == []


def test_check_key_type_inconsistency_builds_finding_per_key(mocker):
    mocker.patch.object(checks.queries, "fetch_jsonb_columns", return_value=_ONE_COLUMN)
    mocker.patch.object(
        checks.queries,
        "fetch_key_type_inconsistencies",
        return_value=[{"key_name": "price", "observed_types": ["number", "string"], "occurrences": 42}],
    )

    findings = checks.check_key_type_inconsistency(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "02.03"
    assert findings[0].severity == Severity.MEDIUM
    assert "price" in findings[0].title
    assert "42" in findings[0].observation


def test_check_missing_validation_layer_flags_unvalidated_column(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_jsonb_columns_without_validation",
        return_value=[{"schema_name": "public", "table_name": "products", "column_name": "attrs"}],
    )

    findings = checks.check_missing_validation_layer(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "02.04"
    assert findings[0].severity == Severity.LOW
    assert "products.attrs" in findings[0].title


def test_check_missing_validation_layer_returns_empty_when_no_rows(mocker):
    mocker.patch.object(checks.queries, "fetch_jsonb_columns_without_validation", return_value=[])
    assert checks.check_missing_validation_layer(conn=object(), config=None) == []
