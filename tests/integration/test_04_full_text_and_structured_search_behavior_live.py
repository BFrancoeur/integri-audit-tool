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
    "integri_audit_tool.categories.full_text_and_structured_search_behavior.queries"
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


@pytest.fixture(autouse=True)
def _enable_pg_stat_statements(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")


def test_is_pg_stat_statements_available_true_once_extension_created(pg_conn):
    assert queries.is_pg_stat_statements_available(pg_conn) is True


def test_fetch_freetext_and_structured_combination_stats_detects_combined_query(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE c4_stat_combined (id serial PRIMARY KEY, body text, attrs jsonb, "
            "sv tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED)"
        )
        cur.execute("SELECT * FROM c4_stat_combined WHERE sv @@ plainto_tsquery('foo')")
        cur.execute(
            "SELECT * FROM c4_stat_combined WHERE sv @@ plainto_tsquery('foo') "
            "AND attrs @> '{\"active\": true}'"
        )

    stats = queries.fetch_freetext_and_structured_combination_stats(pg_conn)

    assert stats["freetext_statement_count"] >= 2
    assert stats["combined_statement_count"] >= 1


def test_fetch_freetext_ranking_stats_detects_ts_rank_usage(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE c4_stat_ranked (id serial PRIMARY KEY, body text, "
            "sv tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED)"
        )
        cur.execute(
            "SELECT id, ts_rank(sv, plainto_tsquery('foo')) FROM c4_stat_ranked "
            "WHERE sv @@ plainto_tsquery('foo')"
        )

    stats = queries.fetch_freetext_ranking_stats(pg_conn)

    assert stats["freetext_statement_count"] >= 1
    assert stats["ranked_statement_count"] >= 1


def test_fetch_raw_tsquery_usage_flags_raw_call_and_excludes_safe_wrappers(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE c4_stat_rawquery (id serial PRIMARY KEY, body text, "
            "sv tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED)"
        )
        cur.execute("SELECT * FROM c4_stat_rawquery WHERE sv @@ to_tsquery('foo & bar')")
        cur.execute("SELECT * FROM c4_stat_rawquery WHERE sv @@ websearch_to_tsquery('foo bar')")

    stats = queries.fetch_raw_tsquery_usage(pg_conn)

    assert stats["raw_tsquery_statement_count"] >= 1
    assert not any("websearch_to_tsquery" in q for q in (stats["example_queries"] or []))
