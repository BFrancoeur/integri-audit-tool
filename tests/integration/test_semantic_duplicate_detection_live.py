"""Integration coverage for the Semantic Duplicate Detection category's raw
SQL against a real Postgres instance.

Unlike tests/unit/categories/test_semantic_duplicate_detection.py (canned
rows), these validate that the SQL in queries.py is actually correct. Marked
`integration`; run explicitly with `pytest -m integration` (requires Docker).

Table names are prefixed `sdd_` to avoid colliding with other categories'
test tables in the shared, session-scoped test container.
"""

import importlib

import pytest

from integri_audit_tool.fingerprint_config import FingerprintConfig, FingerprintField

queries = importlib.import_module("integri_audit_tool.categories.semantic_duplicate_detection.queries")

pytestmark = pytest.mark.integration


def _fp_config(**overrides):
    defaults = {
        "schema": "public",
        "table": "sdd_parts",
        "id_column": "id",
        "fields": (FingerprintField(column="grade", normalize=("lowercase", "strip_whitespace")),),
    }
    defaults.update(overrides)
    return FingerprintConfig(**defaults)


def test_fetch_exact_match_duplicates_groups_identical_fingerprints(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE sdd_parts (id serial PRIMARY KEY, grade text)")
        cur.execute("INSERT INTO sdd_parts (grade) VALUES ('1045'), ('1045'), ('  1045  '), ('4140')")

    rows = queries.fetch_exact_match_duplicates(pg_conn, _fp_config())

    dup = next((r for r in rows if r["match_count"] == 3), None)
    assert dup is not None
    assert dup["fingerprint"] == "1045"
    assert not any(r["match_count"] == 1 for r in rows)  # 4140 alone never appears (HAVING count(*) > 1)


def test_fetch_exact_match_duplicates_multi_field_fingerprint(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE sdd_billets (id serial PRIMARY KEY, grade text, dia text)")
        cur.execute(
            "INSERT INTO sdd_billets (grade, dia) VALUES "
            "('1045', '2.000'), ('1045', '2.000'), ('1045', '3.500')"
        )

    config = _fp_config(
        table="sdd_billets",
        fields=(
            FingerprintField(column="grade", normalize=("lowercase",)),
            FingerprintField(column="dia", normalize=("digits_only",)),
        ),
    )
    rows = queries.fetch_exact_match_duplicates(pg_conn, config)

    assert len(rows) == 1
    assert rows[0]["match_count"] == 2


def test_is_pg_trgm_available_true_once_extension_created(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    assert queries.is_pg_trgm_available(pg_conn) is True


def test_fetch_fuzzy_match_candidates_detects_near_duplicate(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        cur.execute("CREATE TABLE sdd_vendors (id serial PRIMARY KEY, name text)")
        cur.execute(
            "INSERT INTO sdd_vendors (name) VALUES "
            "('Nucor Corporation'), ('Nucor Corp'), ('Totally Unrelated Widgets Inc')"
        )

    # similarity('nucorcorporation', 'nucorcorp') is ~0.47 (confirmed
    # empirically) -- 0.4 leaves a comfortable margin below that and above
    # the near-zero similarity to the unrelated third row.
    config = _fp_config(
        table="sdd_vendors",
        fields=(FingerprintField(column="name", normalize=("lowercase", "strip_whitespace")),),
        similarity_threshold=0.4,
    )
    rows = queries.fetch_fuzzy_match_candidates(pg_conn, config)

    assert len(rows) == 1
    pair = {rows[0]["fingerprint_a"], rows[0]["fingerprint_b"]}
    assert pair == {"nucorcorporation", "nucorcorp"}


def test_fetch_fuzzy_match_candidates_excludes_exact_matches_via_distinct(pg_conn):
    # Two rows with the identical fingerprint collapse to one entry in the
    # DISTINCT CTE, so they can never self-pair as a "fuzzy" candidate --
    # that case is fetch_exact_match_duplicates's job, not this one's.
    with pg_conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        cur.execute("CREATE TABLE sdd_exact_only (id serial PRIMARY KEY, name text)")
        cur.execute("INSERT INTO sdd_exact_only (name) VALUES ('acme'), ('acme')")

    config = _fp_config(
        table="sdd_exact_only",
        fields=(FingerprintField(column="name", normalize=("lowercase",)),),
    )
    rows = queries.fetch_fuzzy_match_candidates(pg_conn, config)

    assert rows == []
