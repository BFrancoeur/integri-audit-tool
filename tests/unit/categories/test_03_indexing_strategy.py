"""Category 3 checks are tested against canned row data (no live DB) —
queries.py is what the integration suite validates against real Postgres.
"""

import importlib

from integri_audit_tool.models import Severity

checks = importlib.import_module("integri_audit_tool.categories.03_indexing_strategy.checks")


def test_check_unused_indexes_builds_finding_from_row(mocker):
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

    findings = checks.check_unused_indexes(conn=object(), config=None)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "03.01"
    assert finding.severity == Severity.LOW
    assert "idx_orders_legacy" in finding.title


def test_check_unused_indexes_returns_empty_when_no_rows(mocker):
    mocker.patch.object(checks.queries, "fetch_unused_indexes", return_value=[])
    assert checks.check_unused_indexes(conn=object(), config=None) == []


def test_check_gin_usage_flags_jsonb_column_without_gin(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_jsonb_columns_without_gin",
        return_value=[{"schema_name": "public", "table_name": "products", "column_name": "attributes"}],
    )

    findings = checks.check_gin_usage(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_id == "03.02"
    assert findings[0].severity == Severity.MEDIUM
    assert "products.attributes" in findings[0].title


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
    assert findings[0].check_id == "03.04"
    assert "customer_id" in findings[0].title
