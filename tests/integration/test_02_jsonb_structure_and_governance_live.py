"""Integration coverage for category 2's raw SQL against a real Postgres instance.

Unlike tests/unit/categories/test_02_jsonb_structure_and_governance.py (canned
rows), these validate that the SQL in queries.py is actually correct —
important here since, unlike categories 1 and 3, these queries inspect JSONB
row *data*, not just catalog metadata. Marked `integration`; run explicitly
with `pytest -m integration` (requires Docker).

Table names are prefixed `c2_` to avoid colliding with other categories' test
tables in the shared, session-scoped test container.
"""

import importlib

import pytest

queries = importlib.import_module("integri_audit_tool.categories.jsonb_structure_and_governance.queries")

pytestmark = pytest.mark.integration


def test_fetch_jsonb_columns_finds_declared_jsonb_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c2_products (id serial PRIMARY KEY, attrs jsonb)")

    rows = queries.fetch_jsonb_columns(pg_conn)

    assert any(r["table_name"] == "c2_products" and r["column_name"] == "attrs" for r in rows)


def test_fetch_jsonb_columns_without_validation_distinguishes_checked_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c2_unvalidated (id serial PRIMARY KEY, attrs jsonb)")
        cur.execute(
            "CREATE TABLE c2_validated (id serial PRIMARY KEY, attrs jsonb, "
            "CONSTRAINT attrs_has_type CHECK (attrs ? 'type'))"
        )

    rows = queries.fetch_jsonb_columns_without_validation(pg_conn)

    assert any(r["table_name"] == "c2_unvalidated" for r in rows)
    assert not any(r["table_name"] == "c2_validated" for r in rows)


def test_fetch_key_naming_variants_flags_case_and_underscore_variants(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c2_widgets (id serial PRIMARY KEY, attrs jsonb)")
        cur.execute(
            "INSERT INTO c2_widgets (attrs) VALUES ('{\"diameter_in\": 5}'), ('{\"diameterIn\": 6}')"
        )

    rows = queries.fetch_key_naming_variants(pg_conn, "public", "c2_widgets", "attrs")

    variant = next((r for r in rows if r["normalized_key"] == "diameterin"), None)
    assert variant is not None
    assert set(variant["observed_keys"]) == {"diameter_in", "diameterIn"}


def test_fetch_key_type_inconsistencies_flags_mixed_types_for_same_key(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c2_orders (id serial PRIMARY KEY, meta jsonb)")
        cur.execute("INSERT INTO c2_orders (meta) VALUES ('{\"price\": 10}'), ('{\"price\": \"ten\"}')")

    rows = queries.fetch_key_type_inconsistencies(pg_conn, "public", "c2_orders", "meta")

    row = next((r for r in rows if r["key_name"] == "price"), None)
    assert row is not None
    assert set(row["observed_types"]) == {"number", "string"}
    assert row["occurrences"] == 2


def test_fetch_rare_jsonb_keys_flags_key_below_threshold(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c2_legacy_docs (id serial PRIMARY KEY, doc jsonb)")
        cur.execute(
            "INSERT INTO c2_legacy_docs (doc) "
            "SELECT jsonb_build_object('common_key', g) FROM generate_series(1, 100) g"
        )
        cur.execute("UPDATE c2_legacy_docs SET doc = doc || '{\"legacy_key\": true}'::jsonb WHERE id = 1")

    rows = queries.fetch_rare_jsonb_keys(pg_conn, "public", "c2_legacy_docs", "doc")

    row = next((r for r in rows if r["key_name"] == "legacy_key"), None)
    assert row is not None
    assert row["occurrence_count"] == 1
    assert not any(r["key_name"] == "common_key" for r in rows)


def test_fetch_rare_jsonb_keys_skips_when_sample_too_small(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c2_tiny_docs (id serial PRIMARY KEY, doc jsonb)")
        cur.execute("INSERT INTO c2_tiny_docs (doc) VALUES ('{\"a\": 1}'), ('{\"a\": 1, \"b\": 2}')")

    rows = queries.fetch_rare_jsonb_keys(pg_conn, "public", "c2_tiny_docs", "doc")

    assert rows == []
