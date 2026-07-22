"""Category 4 checks are tested against canned row data (no live DB) —
queries.py is what the integration suite validates against real Postgres.
"""

import importlib

from integri_audit_tool.models import Severity

checks = importlib.import_module(
    "integri_audit_tool.categories.04_full_text_and_structured_search_behavior.checks"
)


def test_is_applicable_true_when_tsvector_columns_exist(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_tsvector_columns",
        return_value=[{"schema_name": "public", "table_name": "articles", "column_name": "search_vector"}],
    )
    assert checks.is_applicable(conn=object()) is True


def test_is_applicable_false_when_no_tsvector_columns(mocker):
    mocker.patch.object(checks.queries, "fetch_tsvector_columns", return_value=[])
    assert checks.is_applicable(conn=object()) is False


def test_check_missing_fulltext_index_flags_unindexed_column(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_tsvector_columns_without_fulltext_index",
        return_value=[{"schema_name": "public", "table_name": "articles", "column_name": "search_vector"}],
    )

    findings = checks.check_missing_fulltext_index(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "04.01"
    assert findings[0].severity == Severity.MEDIUM
    assert "articles.search_vector" in findings[0].title


def test_check_missing_fulltext_index_returns_empty_when_no_rows(mocker):
    mocker.patch.object(checks.queries, "fetch_tsvector_columns_without_fulltext_index", return_value=[])
    assert checks.check_missing_fulltext_index(conn=object(), config=None) == []


def test_check_tsvector_sync_mechanism_flags_unmaintained_column(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_tsvector_columns_without_sync_mechanism",
        return_value=[{"schema_name": "public", "table_name": "products", "column_name": "search_vector"}],
    )

    findings = checks.check_tsvector_sync_mechanism(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "04.02"
    assert findings[0].severity == Severity.MEDIUM
    assert "products.search_vector" in findings[0].title


def test_check_tsvector_sync_mechanism_returns_empty_when_no_rows(mocker):
    mocker.patch.object(checks.queries, "fetch_tsvector_columns_without_sync_mechanism", return_value=[])
    assert checks.check_tsvector_sync_mechanism(conn=object(), config=None) == []
