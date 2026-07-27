"""Integration coverage for Lot & Certification Traceability's raw SQL against
a real Postgres instance.

Unlike tests/unit/categories/test_lot_and_certification_traceability.py
(canned rows), these validate that the SQL in queries.py is actually correct.
Marked `integration`; run explicitly with `pytest -m integration` (requires Docker).

Table names are prefixed `lc_` to avoid colliding with other categories' test
tables in the shared, session-scoped test container.
"""

import importlib

import pytest

queries = importlib.import_module(
    "integri_audit_tool.categories.lot_and_certification_traceability.queries"
)

pytestmark = pytest.mark.integration


def test_has_lot_or_certification_signal_true_when_lot_column_present(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE lc_signal_lots (id serial PRIMARY KEY, lot_number text)")

    assert queries.has_lot_or_certification_signal(pg_conn) is True


def test_fetch_lot_shaped_column_null_fractions_flags_high_null_rate(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE lc_lots_nullfrac (id serial PRIMARY KEY, lot_number text)")
        cur.execute(
            "INSERT INTO lc_lots_nullfrac (lot_number) "
            "SELECT CASE WHEN g % 2 = 0 THEN NULL ELSE 'L-' || g END FROM generate_series(1, 40) g"
        )
        cur.execute("ANALYZE lc_lots_nullfrac")

    rows = queries.fetch_lot_shaped_column_null_fractions(pg_conn)

    row = next((r for r in rows if r["table_name"] == "lc_lots_nullfrac"), None)
    assert row is not None
    assert row["null_frac"] > 0.4


def test_fetch_lot_tables_with_unconstrained_cert_link_finds_unconstrained_pairing(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE lc_lots_link (id serial PRIMARY KEY, lot_number text, certification_id int)"
        )

    rows = queries.fetch_lot_tables_with_unconstrained_cert_link(pg_conn)

    assert any(
        r["table_name"] == "lc_lots_link" and r["lot_column"] == "lot_number" and r["link_column"] == "certification_id"
        for r in rows
    )


def test_fetch_lot_tables_with_unconstrained_cert_link_excludes_constrained_pairing(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE lc_certs_ref (id serial PRIMARY KEY)")
        cur.execute(
            "CREATE TABLE lc_lots_constrained (id serial PRIMARY KEY, lot_number text, "
            "certification_id int REFERENCES lc_certs_ref(id))"
        )

    rows = queries.fetch_lot_tables_with_unconstrained_cert_link(pg_conn)

    assert not any(r["table_name"] == "lc_lots_constrained" for r in rows)


def test_fetch_lots_with_unlinked_certification_samples_null_link_rows(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE lc_lots_orphaned (id serial PRIMARY KEY, lot_number text, certification_id int)"
        )
        cur.execute(
            "INSERT INTO lc_lots_orphaned (lot_number, certification_id) VALUES "
            "('L-ORPHAN-1', NULL), ('L-ORPHAN-2', NULL), ('L-LINKED', 1)"
        )

    rows = queries.fetch_lots_with_unlinked_certification(
        pg_conn, "public", "lc_lots_orphaned", "lot_number", "certification_id"
    )

    lot_values = {r["lot_value"] for r in rows}
    assert lot_values == {"L-ORPHAN-1", "L-ORPHAN-2"}
    assert rows[0]["total_unlinked"] == 2


def test_fetch_lot_columns_without_unique_constraint_excludes_uniquely_constrained_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE lc_lots_unique (id serial PRIMARY KEY, lot_number text UNIQUE)")
        cur.execute("CREATE TABLE lc_lots_no_unique (id serial PRIMARY KEY, lot_number text)")

    rows = queries.fetch_lot_columns_without_unique_constraint(pg_conn)
    table_names = {r["table_name"] for r in rows}

    assert "lc_lots_no_unique" in table_names
    assert "lc_lots_unique" not in table_names


def test_fetch_duplicate_lot_values_finds_reused_lot_number(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE lc_lots_dupe (id serial PRIMARY KEY, lot_number text)")
        cur.execute(
            "INSERT INTO lc_lots_dupe (lot_number) VALUES ('L-DUP'), ('L-DUP'), ('L-DUP'), ('L-UNIQUE')"
        )

    rows = queries.fetch_duplicate_lot_values(pg_conn, "public", "lc_lots_dupe", "lot_number")

    assert len(rows) == 1
    assert rows[0]["lot_value"] == "L-DUP"
    assert rows[0]["occurrence_count"] == 3


def test_fetch_cert_jsonb_columns_without_validation_flags_unvalidated_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE lc_lots_certdata (id serial PRIMARY KEY, cert_data jsonb)")

    rows = queries.fetch_cert_jsonb_columns_without_validation(pg_conn)

    assert any(r["table_name"] == "lc_lots_certdata" and r["column_name"] == "cert_data" for r in rows)
