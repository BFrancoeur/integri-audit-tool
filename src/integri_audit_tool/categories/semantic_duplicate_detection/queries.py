"""Raw SQL for the Semantic Duplicate Detection category.

Unlike every other category, this one has no fixed schema knowledge at
all — table/column names and normalization rules come entirely from a
per-engagement FingerprintConfig (see fingerprint_config.py), since "what
makes two rows the same real-world product" is business knowledge no
generic audit tool can guess. All dynamic identifiers are built with
psycopg.sql.Identifier, the same safe-interpolation pattern already
established in jsonb_structure_and_governance and schema_design's
row-sampling checks.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.
"""

from __future__ import annotations

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from integri_audit_tool.fingerprint_config import FingerprintConfig

MAX_DISTINCT_FINGERPRINTS_FOR_FUZZY_MATCH = 2000
"""Fuzzy matching is pairwise (O(n^2)) even restricted to distinct
fingerprints -- this caps the comparison set so a client table with very
high fingerprint cardinality can't turn one audit check into an unbounded
scan. 2000 distinct fingerprints is up to ~2M comparisons worst case,
still fast for pg_trgm's similarity() on short strings."""

# No arbitrary code/eval: each normalization primitive maps to one fixed SQL
# expression template, matching fingerprint_config.NORMALIZE_PRIMITIVES
# exactly. {expr} is filled with the previous step's (or the base column's)
# Composable, so steps chain left-to-right.
_NORMALIZE_SQL_TEMPLATES: dict[str, sql.Composable] = {
    "lowercase": sql.SQL("lower({expr})"),
    "strip_whitespace": sql.SQL("regexp_replace({expr}, '\\s+', '', 'g')"),
    "digits_only": sql.SQL("regexp_replace({expr}, '[^0-9]', '', 'g')"),
    "alphanumeric_only": sql.SQL("regexp_replace({expr}, '[^a-zA-Z0-9]', '', 'g')"),
}


def _build_field_expression(column_name: str, normalize_steps: tuple[str, ...]) -> sql.Composable:
    expr: sql.Composable = sql.SQL("{}::text").format(sql.Identifier(column_name))
    for step in normalize_steps:
        expr = _NORMALIZE_SQL_TEMPLATES[step].format(expr=expr)
    return expr


def _build_fingerprint_expression(config: FingerprintConfig) -> sql.Composable:
    """Concatenates every configured field's normalized expression with a
    '|' separator, coalescing NULLs to '' so one missing field doesn't
    collapse the whole fingerprint to NULL (which would never match
    anything, silently hiding rows that are actually identical elsewhere)."""
    field_exprs = [
        sql.SQL("coalesce({expr}, '')").format(expr=_build_field_expression(f.column, f.normalize))
        for f in config.fields
    ]
    return sql.SQL(" || '|' || ").join(field_exprs)


def fetch_exact_match_duplicates(conn: psycopg.Connection, config: FingerprintConfig) -> list[dict]:
    fingerprint_expr = _build_fingerprint_expression(config)
    query = sql.SQL(
        """
        SELECT
            fingerprint,
            array_agg(row_id ORDER BY row_id) AS matching_ids,
            count(*) AS match_count
        FROM (
            SELECT {id_column} AS row_id, {fingerprint_expr} AS fingerprint
            FROM {schema}.{table}
        ) sub
        WHERE fingerprint <> ''
        GROUP BY fingerprint
        HAVING count(*) > 1
        ORDER BY match_count DESC;
        """
    ).format(
        id_column=sql.Identifier(config.id_column),
        fingerprint_expr=fingerprint_expr,
        schema=sql.Identifier(config.schema),
        table=sql.Identifier(config.table),
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query)
        return cur.fetchall()


_IS_PG_TRGM_AVAILABLE_SQL = "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm';"


def is_pg_trgm_available(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute(_IS_PG_TRGM_AVAILABLE_SQL)
        return cur.fetchone() is not None


def fetch_fuzzy_match_candidates(conn: psycopg.Connection, config: FingerprintConfig) -> list[dict]:
    """Compares every pair of *distinct* fingerprints (capped at
    MAX_DISTINCT_FINGERPRINTS_FOR_FUZZY_MATCH) via pg_trgm's %% operator --
    rows sharing an identical fingerprint are already covered by
    fetch_exact_match_duplicates, so deduplicating first also avoids
    reporting the same pair's similarity (1.0) as a second, redundant finding.

    SET pg_trgm.similarity_threshold governs what the %% operator itself
    considers similar enough to return at all; issued on its own execute()
    since SET doesn't accept a bind parameter at all (Postgres requires a
    literal for GUC values, confirmed empirically -- "syntax error at or
    near $1"). Safe to interpolate directly here since
    fingerprint_config.py already validates similarity_threshold is a
    float in (0, 1] before this is ever called; it can't carry SQL text.
    """
    with conn.cursor() as cur:
        cur.execute(f"SET pg_trgm.similarity_threshold = {config.similarity_threshold}")

    fingerprint_expr = _build_fingerprint_expression(config)
    query = sql.SQL(
        """
        WITH capped_fingerprints AS (
            SELECT DISTINCT {fingerprint_expr} AS fingerprint
            FROM {schema}.{table}
            WHERE {fingerprint_expr} <> ''
            ORDER BY 1
            LIMIT %(max_distinct)s
        )
        SELECT
            a.fingerprint AS fingerprint_a,
            b.fingerprint AS fingerprint_b,
            similarity(a.fingerprint, b.fingerprint) AS sim
        FROM capped_fingerprints a
        JOIN capped_fingerprints b
          ON a.fingerprint %% b.fingerprint AND a.fingerprint < b.fingerprint
        ORDER BY sim DESC;
        """
    ).format(
        fingerprint_expr=fingerprint_expr,
        schema=sql.Identifier(config.schema),
        table=sql.Identifier(config.table),
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, {"max_distinct": MAX_DISTINCT_FINGERPRINTS_FOR_FUZZY_MATCH})
        return cur.fetchall()
