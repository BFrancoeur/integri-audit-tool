"""Category 3 checks are tested against canned row data (no live DB) —
queries.py is what the integration suite validates against real Postgres.
"""

import importlib

from integri_audit_tool.models import Severity

checks = importlib.import_module("integri_audit_tool.categories.indexing_strategy.checks")


def test_unused_index_findings_builds_finding_from_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_unused_indexes",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "idx_orders_legacy",
                "idx_scan": 0,
                "index_size_bytes": 8192,
            }
        ],
    )

    findings = checks._unused_index_findings(conn=object())

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_slug == "unused-indexes"
    assert finding.severity == Severity.LOW
    assert "idx_orders_legacy" in finding.title


def test_unused_index_findings_returns_empty_when_no_rows(mocker):
    mocker.patch.object(checks.queries, "fetch_unused_indexes", return_value=[])
    assert checks._unused_index_findings(conn=object()) == []


def test_unindexed_foreign_key_findings_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_unindexed_foreign_keys",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "order_items",
                "column_name": "order_id",
                "constraint_name": "order_items_order_id_fkey",
            }
        ],
    )

    findings = checks._unindexed_foreign_key_findings(conn=object())

    assert len(findings) == 1
    assert findings[0].check_slug == "unused-indexes"
    assert findings[0].severity == Severity.MEDIUM
    assert "order_items.order_id" in findings[0].title


def test_unindexed_foreign_key_findings_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_unindexed_foreign_keys", return_value=[])
    assert checks._unindexed_foreign_key_findings(conn=object()) == []


def test_seq_scan_heavy_table_findings_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_seq_scan_heavy_tables",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "events",
                "seq_scan": 500,
                "seq_tup_read": 50_000_000,
                "idx_scan": 10,
                "table_bytes": 100_000_000,
            }
        ],
    )

    findings = checks._seq_scan_heavy_table_findings(conn=object())

    assert len(findings) == 1
    assert findings[0].check_slug == "unused-indexes"
    assert findings[0].severity == Severity.MEDIUM
    assert "events" in findings[0].title


def test_seq_scan_heavy_table_findings_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_seq_scan_heavy_tables", return_value=[])
    assert checks._seq_scan_heavy_table_findings(conn=object()) == []


def test_composite_index_order_mismatch_findings_empty_when_pg_stat_statements_unavailable(mocker):
    mocker.patch.object(checks.queries, "is_pg_stat_statements_available", return_value=False)
    mock_fetch = mocker.patch.object(checks.queries, "fetch_composite_indexes")

    findings = checks._composite_index_order_mismatch_findings(conn=object())

    assert findings == []
    mock_fetch.assert_not_called()  # no point enumerating composite indexes if we can't check usage


def test_composite_index_order_mismatch_findings_flags_matched_index(mocker):
    mocker.patch.object(checks.queries, "is_pg_stat_statements_available", return_value=True)
    mocker.patch.object(
        checks.queries,
        "fetch_composite_indexes",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "idx_orders_customer_created",
                "index_columns": ["customer_id", "created_at"],
            }
        ],
    )
    mocker.patch.object(checks.queries, "fetch_queries_mentioning_second_column_not_leading", return_value=3)

    findings = checks._composite_index_order_mismatch_findings(conn=object())

    assert len(findings) == 1
    assert findings[0].check_slug == "unused-indexes"
    assert findings[0].severity == Severity.LOW
    assert "idx_orders_customer_created" in findings[0].title


def test_composite_index_order_mismatch_findings_skips_index_with_no_matches(mocker):
    mocker.patch.object(checks.queries, "is_pg_stat_statements_available", return_value=True)
    mocker.patch.object(
        checks.queries,
        "fetch_composite_indexes",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "orders",
                "index_name": "idx_orders_customer_created",
                "index_columns": ["customer_id", "created_at"],
            }
        ],
    )
    mocker.patch.object(checks.queries, "fetch_queries_mentioning_second_column_not_leading", return_value=0)

    findings = checks._composite_index_order_mismatch_findings(conn=object())

    assert findings == []


def test_check_unused_indexes_combines_all_four_sources(mocker):
    mocker.patch.object(
        checks,
        "_unused_index_findings",
        return_value=["unused"],
    )
    mocker.patch.object(checks, "_unindexed_foreign_key_findings", return_value=["fk"])
    mocker.patch.object(checks, "_seq_scan_heavy_table_findings", return_value=["seqscan"])
    mocker.patch.object(checks, "_composite_index_order_mismatch_findings", return_value=["composite"])

    findings = checks.check_unused_indexes(conn=object(), config=None)

    assert findings == ["unused", "fk", "seqscan", "composite"]


def test_check_gin_usage_flags_jsonb_column_without_gin(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_jsonb_columns_without_gin",
        return_value=[{"schema_name": "public", "table_name": "products", "column_name": "attributes"}],
    )

    findings = checks.check_gin_usage(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "gin-usage"
    assert findings[0].severity == Severity.MEDIUM
    assert "products.attributes" in findings[0].title


def test_check_high_selectivity_columns_without_index_flags_high_ratio(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_high_selectivity_columns_without_index",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "orders",
                "column_name": "external_ref",
                "n_distinct": -0.95,
                "n_live_tup": 10000,
            }
        ],
    )

    findings = checks.check_high_selectivity_columns_without_index(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "high-selectivity-columns-without-index"
    assert findings[0].severity == Severity.LOW
    assert "orders.external_ref" in findings[0].title


def test_check_high_selectivity_columns_without_index_skips_low_ratio(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_high_selectivity_columns_without_index",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "orders",
                "column_name": "region",
                "n_distinct": 5,
                "n_live_tup": 10000,
            }
        ],
    )

    findings = checks.check_high_selectivity_columns_without_index(conn=object(), config=None)

    assert findings == []


def test_check_unpromoted_jsonb_range_queries_empty_when_pg_stat_statements_unavailable(mocker):
    mocker.patch.object(checks.queries, "is_pg_stat_statements_available", return_value=False)
    mock_fetch = mocker.patch.object(checks.queries, "fetch_jsonb_columns")

    findings = checks.check_unpromoted_jsonb_range_queries(conn=object(), config=None)

    assert findings == []
    mock_fetch.assert_not_called()


def test_check_unpromoted_jsonb_range_queries_flags_matched_column(mocker):
    mocker.patch.object(checks.queries, "is_pg_stat_statements_available", return_value=True)
    mocker.patch.object(
        checks.queries,
        "fetch_jsonb_columns",
        return_value=[{"schema_name": "public", "table_name": "products", "column_name": "attributes"}],
    )
    mocker.patch.object(checks.queries, "fetch_jsonb_range_query_candidate_count", return_value=2)

    findings = checks.check_unpromoted_jsonb_range_queries(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "unpromoted-jsonb-range-queries"
    assert findings[0].severity == Severity.LOW
    assert "products.attributes" in findings[0].title


def test_check_unpromoted_jsonb_range_queries_skips_column_with_no_matches(mocker):
    mocker.patch.object(checks.queries, "is_pg_stat_statements_available", return_value=True)
    mocker.patch.object(
        checks.queries,
        "fetch_jsonb_columns",
        return_value=[{"schema_name": "public", "table_name": "products", "column_name": "attributes"}],
    )
    mocker.patch.object(checks.queries, "fetch_jsonb_range_query_candidate_count", return_value=0)

    findings = checks.check_unpromoted_jsonb_range_queries(conn=object(), config=None)

    assert findings == []


def test_check_excessive_indexing_write_amplification_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_high_write_tables_with_many_indexes",
        return_value=[
            {"schema_name": "public", "table_name": "events", "write_count": 500_000, "index_count": 9}
        ],
    )

    findings = checks.check_excessive_indexing_write_amplification(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "excessive-indexing-write-amplification"
    assert findings[0].severity == Severity.MEDIUM
    assert "events" in findings[0].title


def test_check_excessive_indexing_write_amplification_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_high_write_tables_with_many_indexes", return_value=[])
    assert checks.check_excessive_indexing_write_amplification(conn=object(), config=None) == []


def test_check_underused_partial_indexes_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_non_partial_indexes_on_flag_columns",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "users",
                "index_name": "idx_users_active",
                "column_name": "active",
                "index_def": "CREATE INDEX idx_users_active ON users (active)",
            }
        ],
    )

    findings = checks.check_underused_partial_indexes(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "underused-partial-indexes"
    assert findings[0].severity == Severity.LOW
    assert "idx_users_active" in findings[0].title


def test_check_underused_partial_indexes_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_non_partial_indexes_on_flag_columns", return_value=[])
    assert checks.check_underused_partial_indexes(conn=object(), config=None) == []


def test_check_redundant_indexes_flags_overlapping_group(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_indexes_sharing_leading_column",
        return_value=[
            {
                "table_name": "orders",
                "leading_column": "customer_id",
                "index_names": ["idx_orders_customer", "idx_orders_customer_created"],
                "index_defs": [
                    "CREATE INDEX idx_orders_customer ON orders (customer_id)",
                    "CREATE INDEX idx_orders_customer_created ON orders (customer_id, created_at)",
                ],
            }
        ],
    )

    findings = checks.check_redundant_indexes(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "redundant-indexes"
    assert "customer_id" in findings[0].title
