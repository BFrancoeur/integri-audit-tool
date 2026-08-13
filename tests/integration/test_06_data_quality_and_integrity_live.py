"""Integration coverage for category 6's raw SQL against a real Postgres instance.

Unlike tests/unit/categories/test_06_data_quality_and_integrity.py (canned
rows), these validate that the SQL in queries.py is actually correct. Marked
`integration`; run explicitly with `pytest -m integration` (requires Docker).

Table names are prefixed `c6_` to avoid colliding with other categories' test
tables in the shared, session-scoped test container. Every test explicitly
runs ANALYZE after inserting data — pg_stats (what queries.py reads) is only
populated by ANALYZE, and a freshly-created/loaded table won't appear in it
at all until then.

Tables use 100+ rows so they clear MIN_LIVE_ROWS_FOR_STATS (20).
"""

import importlib

import pytest

queries = importlib.import_module("integri_audit_tool.categories.data_quality_and_integrity.queries")

pytestmark = pytest.mark.integration


def test_fetch_nullable_column_null_fractions_reports_high_null_rate(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c6_orders (id serial PRIMARY KEY, notes text)")
        cur.execute(
            "INSERT INTO c6_orders (notes) "
            "SELECT CASE WHEN g <= 80 THEN NULL ELSE 'note ' || g END FROM generate_series(1, 100) g"
        )
        cur.execute("ANALYZE c6_orders")

    rows = queries.fetch_nullable_column_null_fractions(pg_conn)

    row = next((r for r in rows if r["table_name"] == "c6_orders" and r["column_name"] == "notes"), None)
    assert row is not None
    assert row["null_frac"] == pytest.approx(0.8, abs=0.05)


def test_fetch_nullable_column_null_fractions_reports_zero_for_always_populated(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c6_customers (id serial PRIMARY KEY, email text)")
        cur.execute(
            "INSERT INTO c6_customers (email) SELECT 'user' || g || '@example.com' FROM generate_series(1, 100) g"
        )
        cur.execute("ANALYZE c6_customers")

    rows = queries.fetch_nullable_column_null_fractions(pg_conn)

    row = next(
        (r for r in rows if r["table_name"] == "c6_customers" and r["column_name"] == "email"), None
    )
    assert row is not None
    assert row["null_frac"] == 0


def test_fetch_unvalidated_foreign_keys_flags_not_valid_constraint(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c6_parents (id serial PRIMARY KEY)")
        cur.execute("CREATE TABLE c6_children (id serial PRIMARY KEY, parent_id int)")
        cur.execute(
            "ALTER TABLE c6_children ADD CONSTRAINT c6_children_parent_fk "
            "FOREIGN KEY (parent_id) REFERENCES c6_parents(id) NOT VALID"
        )

    rows = queries.fetch_unvalidated_foreign_keys(pg_conn)

    assert any(r["conname"] == "c6_children_parent_fk" for r in rows)


def test_fetch_columns_without_unique_constraint_distinguishes_constrained_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c6_products (id serial PRIMARY KEY, sku text)")
        cur.execute("INSERT INTO c6_products (sku) SELECT 'SKU-' || g FROM generate_series(1, 100) g")
        cur.execute("CREATE TABLE c6_widgets (id serial PRIMARY KEY, code text UNIQUE)")
        cur.execute("INSERT INTO c6_widgets (code) SELECT 'CODE-' || g FROM generate_series(1, 100) g")
        cur.execute("ANALYZE c6_products")
        cur.execute("ANALYZE c6_widgets")

    rows = queries.fetch_columns_without_unique_constraint(pg_conn)

    sku_row = next((r for r in rows if r["table_name"] == "c6_products" and r["column_name"] == "sku"), None)
    assert sku_row is not None
    assert not any(r["table_name"] == "c6_widgets" and r["column_name"] == "code" for r in rows)


def test_fetch_audit_timestamp_column_null_fractions_detects_gaps(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c6_events (id serial PRIMARY KEY, created_at timestamptz)")
        cur.execute(
            "INSERT INTO c6_events (created_at) "
            "SELECT CASE WHEN g <= 30 THEN NULL ELSE now() END FROM generate_series(1, 100) g"
        )
        cur.execute("ANALYZE c6_events")

    rows = queries.fetch_audit_timestamp_column_null_fractions(pg_conn)

    row = next((r for r in rows if r["table_name"] == "c6_events"), None)
    assert row is not None
    assert row["column_name"] == "created_at"
    assert row["null_frac"] == pytest.approx(0.3, abs=0.05)


def test_fetch_low_cardinality_ungoverned_columns_distinguishes_governed_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c6_ungoverned_orders (id serial PRIMARY KEY, status text)")
        cur.execute(
            "INSERT INTO c6_ungoverned_orders (status) "
            "SELECT (ARRAY['pending','shipped','delivered'])[1 + (g % 3)] FROM generate_series(1, 100) g"
        )
        cur.execute(
            "CREATE TABLE c6_governed_orders (id serial PRIMARY KEY, status text "
            "CHECK (status IN ('pending','shipped','delivered')))"
        )
        cur.execute(
            "INSERT INTO c6_governed_orders (status) "
            "SELECT (ARRAY['pending','shipped','delivered'])[1 + (g % 3)] FROM generate_series(1, 100) g"
        )
        cur.execute("ANALYZE c6_ungoverned_orders")
        cur.execute("ANALYZE c6_governed_orders")

    rows = queries.fetch_low_cardinality_ungoverned_columns(pg_conn)

    assert any(r["table_name"] == "c6_ungoverned_orders" and r["column_name"] == "status" for r in rows)
    assert not any(r["table_name"] == "c6_governed_orders" for r in rows)


def test_fetch_missing_default_on_status_like_columns_distinguishes_defaulted_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c6_accounts_no_default (id serial PRIMARY KEY, is_active boolean NOT NULL)")
        cur.execute(
            "CREATE TABLE c6_accounts_with_default (id serial PRIMARY KEY, "
            "is_active boolean NOT NULL DEFAULT true)"
        )

    rows = queries.fetch_missing_default_on_status_like_columns(pg_conn)

    assert any(r["table_name"] == "c6_accounts_no_default" and r["column_name"] == "is_active" for r in rows)
    assert not any(r["table_name"] == "c6_accounts_with_default" for r in rows)


def test_fetch_unvalidated_fk_detail_and_orphaned_child_rows(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c6_orphan_parents (id serial PRIMARY KEY)")
        cur.execute("INSERT INTO c6_orphan_parents (id) VALUES (1), (2)")
        cur.execute("CREATE TABLE c6_orphan_children (id serial PRIMARY KEY, parent_id int)")
        # Insert an orphaned reference *before* adding the constraint --
        # NOT VALID is exactly what lets this coexist with a constraint that
        # would otherwise reject it.
        cur.execute("INSERT INTO c6_orphan_children (parent_id) VALUES (1), (2), (999)")
        cur.execute(
            "ALTER TABLE c6_orphan_children ADD CONSTRAINT c6_orphan_children_parent_fk "
            "FOREIGN KEY (parent_id) REFERENCES c6_orphan_parents(id) NOT VALID"
        )

    detail_rows = queries.fetch_unvalidated_fk_detail(pg_conn)
    detail = next((r for r in detail_rows if r["conname"] == "c6_orphan_children_parent_fk"), None)
    assert detail is not None
    assert detail["child_column"] == "parent_id"
    assert detail["parent_table"] == "c6_orphan_parents"
    assert detail["parent_column"] == "id"

    orphaned_values = queries.fetch_orphaned_child_rows(
        pg_conn,
        detail["schema_name"],
        detail["table_name"],
        detail["child_column"],
        detail["parent_schema"],
        detail["parent_table"],
        detail["parent_column"],
    )
    assert orphaned_values == [999]


def test_fetch_empty_jsonb_document_stats_counts_empty_documents(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c6_jsonb_docs (id serial PRIMARY KEY, attributes jsonb)")
        cur.execute(
            "INSERT INTO c6_jsonb_docs (attributes) "
            "SELECT CASE WHEN g <= 5 THEN '{}'::jsonb ELSE jsonb_build_object('k', g) END "
            "FROM generate_series(1, 25) g"
        )

    stats = queries.fetch_empty_jsonb_document_stats(pg_conn, "public", "c6_jsonb_docs", "attributes")

    assert stats["sample_size"] == 25
    assert stats["empty_count"] == 5


def test_fetch_empty_jsonb_document_stats_ignores_non_empty_documents(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c6_jsonb_docs_clean (id serial PRIMARY KEY, attributes jsonb)")
        cur.execute(
            "INSERT INTO c6_jsonb_docs_clean (attributes) "
            "SELECT jsonb_build_object('k', g) FROM generate_series(1, 25) g"
        )

    stats = queries.fetch_empty_jsonb_document_stats(pg_conn, "public", "c6_jsonb_docs_clean", "attributes")

    assert stats["sample_size"] == 25
    assert stats["empty_count"] == 0
