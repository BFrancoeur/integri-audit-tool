"""Integration coverage for category 1's raw SQL against a real Postgres instance.

Unlike tests/unit/categories/test_01_schema_design_and_normalization_boundaries.py
(canned rows), these validate that the SQL in queries.py is actually correct.
Marked `integration`; run explicitly with `pytest -m integration` (requires Docker).

Table names are prefixed `c1_` to avoid colliding with other categories' test
tables in the shared, session-scoped test container.
"""

import importlib

import pytest

queries = importlib.import_module(
    "integri_audit_tool.categories.schema_design_and_normalization_boundaries.queries"
)

pytestmark = pytest.mark.integration


def test_fetch_fk_like_columns_without_fk_flags_unconstrained_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c1_orders (id serial PRIMARY KEY, customer_id integer)")
        cur.execute(
            "CREATE TABLE c1_order_items (id serial PRIMARY KEY, order_id integer REFERENCES c1_orders(id))"
        )

    rows = queries.fetch_fk_like_columns_without_fk(pg_conn)

    assert any(r["table_name"] == "c1_orders" and r["column_name"] == "customer_id" for r in rows)
    assert not any(r["table_name"] == "c1_order_items" and r["column_name"] == "order_id" for r in rows)


def test_fetch_columns_with_name_or_type_drift_flags_inconsistent_concept(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c1_table_a (id serial PRIMARY KEY, created_at timestamptz)")
        cur.execute('CREATE TABLE c1_table_b (id serial PRIMARY KEY, "createdAt" text)')

    rows = queries.fetch_columns_with_name_or_type_drift(pg_conn)

    drifted = next((r for r in rows if r["normalized_name"] == "createdat"), None)
    assert drifted is not None
    assert set(drifted["observed_names"]) == {"created_at", "createdAt"}
    assert set(drifted["observed_types"]) == {"timestamp with time zone", "text"}


def test_fetch_tables_without_primary_key_flags_pk_less_table(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c1_logs (id integer, message text)")

    rows = queries.fetch_tables_without_primary_key(pg_conn)

    assert any(r["table_name"] == "c1_logs" for r in rows)


def test_fetch_primary_key_column_types_reports_types_per_table(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c1_pktype_uuid (id uuid PRIMARY KEY, name text)")
        cur.execute("CREATE TABLE c1_pktype_int (id serial PRIMARY KEY)")

    rows = queries.fetch_primary_key_column_types(pg_conn)
    types = {r["table_name"]: r["data_type"] for r in rows}

    assert types.get("c1_pktype_uuid") == "uuid"
    assert types.get("c1_pktype_int") == "integer"


def test_fetch_all_columns_returns_schema_table_column_and_type(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c1_pivot_candidate (jan_qty integer, feb_qty integer, sku text)")

    rows = queries.fetch_all_columns(pg_conn)

    by_column = {
        r["column_name"]: r["data_type"] for r in rows if r["table_name"] == "c1_pivot_candidate"
    }
    assert by_column == {"jan_qty": "integer", "feb_qty": "integer", "sku": "text"}


def test_fetch_text_column_value_sample_returns_non_null_values(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c1_weights (id serial PRIMARY KEY, weight_kg text)")
        cur.execute("INSERT INTO c1_weights (weight_kg) VALUES ('12.5'), ('8.0'), (NULL)")

    values = queries.fetch_text_column_value_sample(pg_conn, "public", "c1_weights", "weight_kg")

    assert set(values) == {"12.5", "8.0"}


def test_fetch_varchar_without_length_flags_bare_varchar(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c1_skus (id serial PRIMARY KEY, sku varchar, code varchar(20))")

    rows = queries.fetch_varchar_without_length(pg_conn)

    assert any(r["table_name"] == "c1_skus" and r["column_name"] == "sku" for r in rows)
    assert not any(r["table_name"] == "c1_skus" and r["column_name"] == "code" for r in rows)


def test_fetch_money_type_usage_detects_money_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c1_invoices (id serial PRIMARY KEY, total money, subtotal numeric(10,2))")

    rows = queries.fetch_money_type_usage(pg_conn)

    assert any(r["table_name"] == "c1_invoices" and r["column_name"] == "total" for r in rows)
    assert not any(r["column_name"] == "subtotal" for r in rows)


def test_fetch_on_delete_cascade_constraints_detects_cascade(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c1_contacts (id serial PRIMARY KEY)")
        cur.execute(
            "CREATE TABLE c1_customers (id serial PRIMARY KEY, "
            "primary_contact_id integer REFERENCES c1_contacts(id) ON DELETE CASCADE)"
        )
        cur.execute("CREATE TABLE c1_no_cascade_child (id serial PRIMARY KEY, "
                    "contact_id integer REFERENCES c1_contacts(id))")

    rows = queries.fetch_on_delete_cascade_constraints(pg_conn)

    assert any(r["table_name"] == "c1_customers" and r["parent_table_name"] == "c1_contacts" for r in rows)
    assert not any(r["table_name"] == "c1_no_cascade_child" for r in rows)
