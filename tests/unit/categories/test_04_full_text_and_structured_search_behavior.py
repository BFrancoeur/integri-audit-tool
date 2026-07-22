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


def _mock_pg_stat_statements_available(mocker, available: bool):
    mocker.patch.object(checks.queries, "is_pg_stat_statements_available", return_value=available)


def test_check_combined_structured_and_freetext_queries_informational_when_unavailable(mocker):
    _mock_pg_stat_statements_available(mocker, False)

    findings = checks.check_combined_structured_and_freetext_queries(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "04.03"
    assert findings[0].severity == Severity.INFORMATIONAL


def test_check_combined_structured_and_freetext_queries_flags_when_none_combined(mocker):
    _mock_pg_stat_statements_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_freetext_and_structured_combination_stats",
        return_value={"freetext_statement_count": 5, "combined_statement_count": 0},
    )

    findings = checks.check_combined_structured_and_freetext_queries(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "04.03"
    assert findings[0].severity == Severity.LOW


def test_check_combined_structured_and_freetext_queries_empty_when_some_combined(mocker):
    _mock_pg_stat_statements_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_freetext_and_structured_combination_stats",
        return_value={"freetext_statement_count": 5, "combined_statement_count": 2},
    )
    assert checks.check_combined_structured_and_freetext_queries(conn=object(), config=None) == []


def test_check_combined_structured_and_freetext_queries_empty_when_no_freetext_at_all(mocker):
    _mock_pg_stat_statements_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_freetext_and_structured_combination_stats",
        return_value={"freetext_statement_count": 0, "combined_statement_count": 0},
    )
    assert checks.check_combined_structured_and_freetext_queries(conn=object(), config=None) == []


def test_check_relevance_ranking_informational_when_unavailable(mocker):
    _mock_pg_stat_statements_available(mocker, False)

    findings = checks.check_relevance_ranking(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "04.04"
    assert findings[0].severity == Severity.INFORMATIONAL


def test_check_relevance_ranking_flags_when_none_ranked(mocker):
    _mock_pg_stat_statements_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_freetext_ranking_stats",
        return_value={"freetext_statement_count": 3, "ranked_statement_count": 0},
    )

    findings = checks.check_relevance_ranking(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "04.04"
    assert findings[0].severity == Severity.LOW


def test_check_relevance_ranking_empty_when_some_ranked(mocker):
    _mock_pg_stat_statements_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_freetext_ranking_stats",
        return_value={"freetext_statement_count": 3, "ranked_statement_count": 1},
    )
    assert checks.check_relevance_ranking(conn=object(), config=None) == []


def test_check_relevance_ranking_empty_when_no_freetext_at_all(mocker):
    _mock_pg_stat_statements_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_freetext_ranking_stats",
        return_value={"freetext_statement_count": 0, "ranked_statement_count": 0},
    )
    assert checks.check_relevance_ranking(conn=object(), config=None) == []


def test_check_safe_tsquery_parsing_informational_when_unavailable(mocker):
    _mock_pg_stat_statements_available(mocker, False)

    findings = checks.check_safe_tsquery_parsing(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "04.05"
    assert findings[0].severity == Severity.INFORMATIONAL


def test_check_safe_tsquery_parsing_flags_raw_usage(mocker):
    _mock_pg_stat_statements_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_raw_tsquery_usage",
        return_value={
            "raw_tsquery_statement_count": 2,
            "example_queries": ["SELECT * FROM articles WHERE sv @@ to_tsquery($1)"],
        },
    )

    findings = checks.check_safe_tsquery_parsing(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "04.05"
    assert findings[0].severity == Severity.MEDIUM
    assert "to_tsquery" in findings[0].evidence


def test_check_safe_tsquery_parsing_empty_when_no_raw_usage(mocker):
    _mock_pg_stat_statements_available(mocker, True)
    mocker.patch.object(
        checks.queries,
        "fetch_raw_tsquery_usage",
        return_value={"raw_tsquery_statement_count": 0, "example_queries": []},
    )
    assert checks.check_safe_tsquery_parsing(conn=object(), config=None) == []
