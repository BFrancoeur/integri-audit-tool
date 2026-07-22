"""Integration coverage for category 4's raw SQL against a real Postgres instance.

Unlike tests/unit/categories/test_04_full_text_and_structured_search_behavior.py
(canned rows), these validate that the SQL in queries.py is actually correct.
Marked `integration`; run explicitly with `pytest -m integration` (requires Docker).

Table names are prefixed `c4_` to avoid colliding with other categories' test
tables in the shared, session-scoped test container.
"""

import importlib

import pytest

queries = importlib.import_module(
    "integri_audit_tool.categories.04_full_text_and_structured_search_behavior.queries"
)

pytestmark = pytest.mark.integration


def test_fetch_tsvector_columns_finds_declared_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE c4_articles (id serial PRIMARY KEY, body text, "
            "search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED)"
        )

    rows = queries.fetch_tsvector_columns(pg_conn)

    assert any(r["table_name"] == "c4_articles" and r["column_name"] == "search_vector" for r in rows)


def test_fetch_tsvector_columns_without_fulltext_index_distinguishes_indexed_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE c4_idx_ok (id serial PRIMARY KEY, body text, "
            "sv tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED)"
        )
        cur.execute("CREATE INDEX c4_idx_ok_gin ON c4_idx_ok USING gin (sv)")
        cur.execute(
            "CREATE TABLE c4_idx_missing (id serial PRIMARY KEY, body text, "
            "sv tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED)"
        )

    rows = queries.fetch_tsvector_columns_without_fulltext_index(pg_conn)

    assert any(r["table_name"] == "c4_idx_missing" for r in rows)
    assert not any(r["table_name"] == "c4_idx_ok" for r in rows)


def test_fetch_tsvector_columns_without_sync_mechanism_distinguishes_generated_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE c4_sync_generated (id serial PRIMARY KEY, body text, "
            "sv tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED)"
        )
        cur.execute("CREATE TABLE c4_sync_manual (id serial PRIMARY KEY, body text, sv tsvector)")

    rows = queries.fetch_tsvector_columns_without_sync_mechanism(pg_conn)

    assert any(r["table_name"] == "c4_sync_manual" for r in rows)
    assert not any(r["table_name"] == "c4_sync_generated" for r in rows)
