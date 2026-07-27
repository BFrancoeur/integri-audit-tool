"""Category 11 checks are tested against canned row data (no live DB) —
queries.py is what the integration suite validates against real Postgres.
"""

import importlib

from integri_audit_tool.models import Severity

checks = importlib.import_module(
    "integri_audit_tool.categories.documentation_and_institutional_knowledge.checks"
)


def test_check_table_documentation_coverage_flags_when_none_documented(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_table_documentation_coverage",
        return_value={"total_tables": 10, "documented_tables": 0},
    )

    findings = checks.check_table_documentation_coverage(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "table-documentation-coverage"
    assert findings[0].severity == Severity.LOW


def test_check_table_documentation_coverage_empty_when_some_documented(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_table_documentation_coverage",
        return_value={"total_tables": 10, "documented_tables": 2},
    )
    assert checks.check_table_documentation_coverage(conn=object(), config=None) == []


def test_check_table_documentation_coverage_empty_when_no_tables(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_table_documentation_coverage",
        return_value={"total_tables": 0, "documented_tables": 0},
    )
    assert checks.check_table_documentation_coverage(conn=object(), config=None) == []


def test_check_undocumented_jsonb_column_rationale_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_undocumented_jsonb_columns",
        return_value=[{"schema_name": "public", "table_name": "products", "column_name": "attrs"}],
    )

    findings = checks.check_undocumented_jsonb_column_rationale(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "undocumented-jsonb-column-rationale"
    assert findings[0].severity == Severity.LOW
    assert "products.attrs" in findings[0].title


def test_check_undocumented_jsonb_column_rationale_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_undocumented_jsonb_columns", return_value=[])
    assert checks.check_undocumented_jsonb_column_rationale(conn=object(), config=None) == []


def test_check_jsonb_without_schema_registry_flags_when_missing(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_jsonb_and_registry_presence",
        return_value={"has_jsonb_columns": True, "has_registry_table": False},
    )

    findings = checks.check_jsonb_without_schema_registry(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "jsonb-without-schema-registry"
    assert findings[0].severity == Severity.LOW


def test_check_jsonb_without_schema_registry_empty_when_registry_present(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_jsonb_and_registry_presence",
        return_value={"has_jsonb_columns": True, "has_registry_table": True},
    )
    assert checks.check_jsonb_without_schema_registry(conn=object(), config=None) == []


def test_check_jsonb_without_schema_registry_empty_when_no_jsonb(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_jsonb_and_registry_presence",
        return_value={"has_jsonb_columns": False, "has_registry_table": False},
    )
    assert checks.check_jsonb_without_schema_registry(conn=object(), config=None) == []
