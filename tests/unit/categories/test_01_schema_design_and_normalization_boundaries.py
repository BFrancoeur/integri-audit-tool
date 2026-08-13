"""Category 1 checks are tested against canned row data (no live DB) —
queries.py is what the integration suite validates against real Postgres.
"""

import importlib

from integri_audit_tool.models import Severity

checks = importlib.import_module(
    "integri_audit_tool.categories.schema_design_and_normalization_boundaries.checks"
)


def test_check_missing_foreign_keys_flags_unconstrained_fk_shaped_column(mocker):
    """Severity is HIGH (bumped from MEDIUM in the SOP merge) -- the SOP
    calls this one of the highest-severity findings in any audit, an
    explicit, intentional behavior change."""
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
    mocker.patch.object(checks.queries, "fetch_on_delete_cascade_constraints", return_value=[])

    findings = checks.check_missing_foreign_keys(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "missing-foreign-keys"
    assert findings[0].severity == Severity.HIGH
    assert "orders.customer_id" in findings[0].title


def test_check_missing_foreign_keys_returns_empty_when_no_rows(mocker):
    mocker.patch.object(checks.queries, "fetch_fk_like_columns_without_fk", return_value=[])
    mocker.patch.object(checks.queries, "fetch_on_delete_cascade_constraints", return_value=[])
    assert checks.check_missing_foreign_keys(conn=object(), config=None) == []


def test_check_missing_foreign_keys_flags_cascade_on_unowned_looking_child(mocker):
    mocker.patch.object(checks.queries, "fetch_fk_like_columns_without_fk", return_value=[])
    mocker.patch.object(
        checks.queries,
        "fetch_on_delete_cascade_constraints",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "customers",
                "conname": "customers_primary_contact_id_fkey",
                "parent_table_name": "contacts",
            }
        ],
    )

    findings = checks.check_missing_foreign_keys(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "missing-foreign-keys"
    assert findings[0].severity == Severity.MEDIUM
    assert "customers" in findings[0].title and "contacts" in findings[0].title


def test_check_missing_foreign_keys_does_not_flag_cascade_on_owned_looking_child(mocker):
    mocker.patch.object(checks.queries, "fetch_fk_like_columns_without_fk", return_value=[])
    mocker.patch.object(
        checks.queries,
        "fetch_on_delete_cascade_constraints",
        return_value=[
            {
                "schema_name": "public",
                "table_name": "order_items",
                "conname": "order_items_order_id_fkey",
                "parent_table_name": "orders",
            }
        ],
    )

    findings = checks.check_missing_foreign_keys(conn=object(), config=None)

    assert findings == []


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


def _column_row(table_name, column_name, data_type, schema_name="public"):
    return {
        "schema_name": schema_name,
        "table_name": table_name,
        "column_name": column_name,
        "data_type": data_type,
    }


def test_check_repeating_column_groups_flags_numbered_warehouse_pivot(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_all_columns",
        return_value=[
            _column_row("inventory_snapshot", "warehouse_1_stock", "integer"),
            _column_row("inventory_snapshot", "warehouse_2_stock", "integer"),
            _column_row("inventory_snapshot", "warehouse_3_stock", "integer"),
            _column_row("inventory_snapshot", "warehouse_id", "integer"),
            _column_row("inventory_snapshot", "sku", "text"),
        ],
    )

    findings = checks.check_repeating_column_groups(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "repeating-column-groups"
    assert findings[0].severity == Severity.MEDIUM
    assert "inventory_snapshot" in findings[0].title


def test_check_repeating_column_groups_does_not_flag_alphabetic_period_pivot(mocker):
    """jan_qty/feb_qty/mar_qty is a real pivot but isn't caught -- documented
    limitation, since catching it would require hardcoding a month-name
    vocabulary this check deliberately avoids."""
    mocker.patch.object(
        checks.queries,
        "fetch_all_columns",
        return_value=[
            _column_row("inventory_snapshot", "jan_qty", "integer"),
            _column_row("inventory_snapshot", "feb_qty", "integer"),
            _column_row("inventory_snapshot", "mar_qty", "integer"),
        ],
    )

    findings = checks.check_repeating_column_groups(conn=object(), config=None)

    assert findings == []


def test_check_repeating_column_groups_does_not_flag_alphabetic_suffix_family(mocker):
    """created_at/updated_at/deleted_at share a suffix and type but aren't a
    numbered enumeration -- must not be flagged as a repeating group."""
    mocker.patch.object(
        checks.queries,
        "fetch_all_columns",
        return_value=[
            _column_row("orders", "created_at", "timestamp with time zone"),
            _column_row("orders", "updated_at", "timestamp with time zone"),
            _column_row("orders", "deleted_at", "timestamp with time zone"),
        ],
    )

    findings = checks.check_repeating_column_groups(conn=object(), config=None)

    assert findings == []


def test_check_repeating_column_groups_does_not_flag_pair_below_min_size(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_all_columns",
        return_value=[
            _column_row("projects", "q1_budget", "numeric"),
            _column_row("projects", "q2_budget", "numeric"),
        ],
    )

    findings = checks.check_repeating_column_groups(conn=object(), config=None)

    assert findings == []


def test_check_repeating_column_groups_returns_empty_when_no_rows(mocker):
    mocker.patch.object(checks.queries, "fetch_all_columns", return_value=[])
    assert checks.check_repeating_column_groups(conn=object(), config=None) == []


def _text_column(table_name, column_name, schema_name="public"):
    return {"schema_name": schema_name, "table_name": table_name, "column_name": column_name}


def test_check_structured_data_stored_as_text_flags_numeric_shaped_column(mocker):
    mocker.patch.object(
        checks.queries, "fetch_text_typed_columns", return_value=[_text_column("parts", "weight_kg")]
    )
    mocker.patch.object(
        checks.queries,
        "fetch_text_column_value_sample",
        return_value=[str(n) for n in range(20)],
    )
    mocker.patch.object(checks.queries, "fetch_varchar_without_length", return_value=[])
    mocker.patch.object(checks.queries, "fetch_money_type_usage", return_value=[])

    findings = checks.check_structured_data_stored_as_text(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "structured-data-stored-as-text"
    assert findings[0].severity == Severity.MEDIUM
    assert "Numeric data stored as text" in findings[0].title


def test_check_structured_data_stored_as_text_flags_date_shaped_column(mocker):
    mocker.patch.object(
        checks.queries, "fetch_text_typed_columns", return_value=[_text_column("orders", "ship_date")]
    )
    mocker.patch.object(
        checks.queries,
        "fetch_text_column_value_sample",
        return_value=["2026-01-0" + str(n % 9 + 1) for n in range(15)],
    )
    mocker.patch.object(checks.queries, "fetch_varchar_without_length", return_value=[])
    mocker.patch.object(checks.queries, "fetch_money_type_usage", return_value=[])

    findings = checks.check_structured_data_stored_as_text(conn=object(), config=None)

    assert len(findings) == 1
    assert "Date data stored as text" in findings[0].title


def test_check_structured_data_stored_as_text_flags_delimited_list_column(mocker):
    mocker.patch.object(
        checks.queries, "fetch_text_typed_columns", return_value=[_text_column("parts", "tags")]
    )
    mocker.patch.object(
        checks.queries,
        "fetch_text_column_value_sample",
        return_value=["red,blue,green" for _ in range(15)],
    )
    mocker.patch.object(checks.queries, "fetch_varchar_without_length", return_value=[])
    mocker.patch.object(checks.queries, "fetch_money_type_usage", return_value=[])

    findings = checks.check_structured_data_stored_as_text(conn=object(), config=None)

    assert len(findings) == 1
    assert "Delimited list data stored as text" in findings[0].title


def test_check_structured_data_stored_as_text_does_not_flag_free_text(mocker):
    mocker.patch.object(
        checks.queries, "fetch_text_typed_columns", return_value=[_text_column("parts", "description")]
    )
    mocker.patch.object(
        checks.queries,
        "fetch_text_column_value_sample",
        return_value=["A high-strength fastener for structural applications." for _ in range(15)],
    )
    mocker.patch.object(checks.queries, "fetch_varchar_without_length", return_value=[])
    mocker.patch.object(checks.queries, "fetch_money_type_usage", return_value=[])

    findings = checks.check_structured_data_stored_as_text(conn=object(), config=None)

    assert findings == []


def test_check_structured_data_stored_as_text_skips_column_below_min_sample_size(mocker):
    mocker.patch.object(
        checks.queries, "fetch_text_typed_columns", return_value=[_text_column("parts", "weight_kg")]
    )
    mocker.patch.object(checks.queries, "fetch_text_column_value_sample", return_value=["1", "2", "3"])
    mocker.patch.object(checks.queries, "fetch_varchar_without_length", return_value=[])
    mocker.patch.object(checks.queries, "fetch_money_type_usage", return_value=[])

    findings = checks.check_structured_data_stored_as_text(conn=object(), config=None)

    assert findings == []


def test_check_structured_data_stored_as_text_flags_varchar_without_length(mocker):
    mocker.patch.object(checks.queries, "fetch_text_typed_columns", return_value=[])
    mocker.patch.object(
        checks.queries, "fetch_varchar_without_length", return_value=[_text_column("parts", "sku")]
    )
    mocker.patch.object(checks.queries, "fetch_money_type_usage", return_value=[])

    findings = checks.check_structured_data_stored_as_text(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].severity == Severity.LOW
    assert "varchar with no declared length" in findings[0].title


def test_check_structured_data_stored_as_text_flags_money_type(mocker):
    mocker.patch.object(checks.queries, "fetch_text_typed_columns", return_value=[])
    mocker.patch.object(checks.queries, "fetch_varchar_without_length", return_value=[])
    mocker.patch.object(
        checks.queries, "fetch_money_type_usage", return_value=[_text_column("invoices", "total")]
    )

    findings = checks.check_structured_data_stored_as_text(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].severity == Severity.LOW
    assert "money type usage" in findings[0].title


def test_check_structured_data_stored_as_text_returns_empty_when_no_signals(mocker):
    mocker.patch.object(checks.queries, "fetch_text_typed_columns", return_value=[])
    mocker.patch.object(checks.queries, "fetch_varchar_without_length", return_value=[])
    mocker.patch.object(checks.queries, "fetch_money_type_usage", return_value=[])

    assert checks.check_structured_data_stored_as_text(conn=object(), config=None) == []
