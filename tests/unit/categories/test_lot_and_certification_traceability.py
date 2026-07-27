"""Category Lot & Certification Traceability checks are tested against canned
row data (no live DB) — queries.py is what the integration suite validates
against real Postgres.
"""

import importlib

from integri_audit_tool.models import Severity

checks = importlib.import_module(
    "integri_audit_tool.categories.lot_and_certification_traceability.checks"
)


def test_is_applicable_true_when_signal_present(mocker):
    mocker.patch.object(checks.queries, "has_lot_or_certification_signal", return_value=True)
    assert checks.is_applicable(conn=object()) is True


def test_is_applicable_false_when_no_signal(mocker):
    mocker.patch.object(checks.queries, "has_lot_or_certification_signal", return_value=False)
    assert checks.is_applicable(conn=object()) is False


def test_check_lot_columns_poorly_populated_flags_above_threshold(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_lot_shaped_column_null_fractions",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "shipments",
                "column_name": "lot_number",
                "null_frac": 0.35,
                "n_live_tup": 4000,
            }
        ],
    )

    findings = checks.check_lot_columns_poorly_populated(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "lot-columns-poorly-populated"
    assert findings[0].severity == Severity.HIGH
    assert "shipments.lot_number" in findings[0].title
    assert "35%" in findings[0].observation


def test_check_lot_columns_poorly_populated_skips_below_threshold(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_lot_shaped_column_null_fractions",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "shipments",
                "column_name": "lot_number",
                "null_frac": 0.02,
                "n_live_tup": 4000,
            }
        ],
    )

    assert checks.check_lot_columns_poorly_populated(conn=object(), config=None) == []


def test_check_orphaned_lot_certification_links_itemizes_specific_lot_numbers(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_lot_tables_with_unconstrained_cert_link",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "production_lots",
                "lot_column": "lot_number",
                "link_column": "certification_id",
            }
        ],
    )
    mocker.patch.object(
        checks.queries,
        "fetch_lots_with_unlinked_certification",
        return_value=[
            {"lot_value": "L-2024-0091", "total_unlinked": 2},
            {"lot_value": "L-2024-0143", "total_unlinked": 2},
        ],
    )

    findings = checks.check_orphaned_lot_certification_links(conn=object(), config=None)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_slug == "orphaned-lot-certification-links"
    assert finding.severity == Severity.HIGH
    assert "L-2024-0091" in finding.observation
    assert "L-2024-0143" in finding.observation
    assert "2" in finding.title


def test_check_orphaned_lot_certification_links_notes_truncation_when_sample_is_partial(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_lot_tables_with_unconstrained_cert_link",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "production_lots",
                "lot_column": "lot_number",
                "link_column": "certification_id",
            }
        ],
    )
    mocker.patch.object(
        checks.queries,
        "fetch_lots_with_unlinked_certification",
        return_value=[{"lot_value": "L-1", "total_unlinked": 50}],
    )

    findings = checks.check_orphaned_lot_certification_links(conn=object(), config=None)

    assert "showing 1 of 50" in findings[0].observation


def test_check_orphaned_lot_certification_links_empty_when_no_unlinked_rows(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_lot_tables_with_unconstrained_cert_link",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "production_lots",
                "lot_column": "lot_number",
                "link_column": "certification_id",
            }
        ],
    )
    mocker.patch.object(checks.queries, "fetch_lots_with_unlinked_certification", return_value=[])

    assert checks.check_orphaned_lot_certification_links(conn=object(), config=None) == []


def test_check_duplicate_lot_numbers_itemizes_specific_values(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_lot_columns_without_unique_constraint",
        return_value=[{"schema_name": "public", "table_name": "production_lots", "lot_column": "lot_number"}],
    )
    mocker.patch.object(
        checks.queries,
        "fetch_duplicate_lot_values",
        return_value=[{"lot_value": "L-2024-0091", "occurrence_count": 3}],
    )

    findings = checks.check_duplicate_lot_numbers(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "duplicate-lot-numbers"
    assert findings[0].severity == Severity.HIGH
    assert "L-2024-0091 (x3)" in findings[0].observation


def test_check_duplicate_lot_numbers_empty_when_none_found(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_lot_columns_without_unique_constraint",
        return_value=[{"schema_name": "public", "table_name": "production_lots", "lot_column": "lot_number"}],
    )
    mocker.patch.object(checks.queries, "fetch_duplicate_lot_values", return_value=[])

    assert checks.check_duplicate_lot_numbers(conn=object(), config=None) == []


def test_check_ungoverned_certification_data_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_cert_jsonb_columns_without_validation",
        return_value=[{"schema_name": "public", "table_name": "production_lots", "column_name": "cert_data"}],
    )

    findings = checks.check_ungoverned_certification_data(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "ungoverned-certification-data"
    assert findings[0].severity == Severity.MEDIUM
    assert "production_lots.cert_data" in findings[0].title


def test_check_ungoverned_certification_data_empty_when_none_found(mocker):
    mocker.patch.object(checks.queries, "fetch_cert_jsonb_columns_without_validation", return_value=[])
    assert checks.check_ungoverned_certification_data(conn=object(), config=None) == []
