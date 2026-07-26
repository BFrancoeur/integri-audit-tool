"""Interprets category-4 catalog queries into Finding objects.

One function per rubric checklist bullet (see postgres-database-audit-rubric.md,
"4. Full-Text & Structured Search Behavior"). Each takes a live connection +
config and returns zero or more Findings. Kept separate from queries.py so
this interpretation logic is unit-testable against canned row data without a
live database.
"""

from __future__ import annotations

import psycopg

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import Finding, Severity

from . import queries


def is_applicable(conn: psycopg.Connection) -> bool:
    """Category is N/A when the schema has no tsvector columns at all (per rubric guidance)."""
    return len(queries.fetch_tsvector_columns(conn)) > 0


def check_missing_fulltext_index(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 04.01 — is full-text search using tsvector/tsquery with GIN indexing?"""
    findings = []
    for row in queries.fetch_tsvector_columns_without_fulltext_index(conn):
        findings.append(
            Finding(
                check_slug="missing-fulltext-index",
                title=f"tsvector column without a full-text index: {row['table_name']}.{row['column_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"Column '{row['column_name']}' on {row['schema_name']}.{row['table_name']} is "
                    "tsvector but no GIN or GiST index was found covering it."
                ),
                evidence="Detected via information_schema.columns + pg_indexes (heuristic text match on indexdef).",
                business_impact=(
                    "Full-text queries (@@) against this column will require a sequential scan, which "
                    "won't scale as the table grows."
                ),
                recommended_direction="Add a GIN index (preferred for most workloads) or GiST index on this tsvector column.",
            )
        )
    return findings


def check_tsvector_sync_mechanism(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 04.02 — is the tsvector kept in sync via a generated column or trigger?"""
    findings = []
    for row in queries.fetch_tsvector_columns_without_sync_mechanism(conn):
        findings.append(
            Finding(
                check_slug="tsvector-sync-mechanism",
                title=f"tsvector column without an automatic sync mechanism: {row['table_name']}.{row['column_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"Column '{row['column_name']}' on {row['schema_name']}.{row['table_name']} is tsvector "
                    "but isn't a STORED generated column and the table has no trigger — nothing enforces "
                    "that it stays in sync with its source columns."
                ),
                evidence="Detected via pg_attribute.attgenerated and pg_trigger (heuristic: no triggers on the table at all).",
                business_impact=(
                    "If this column is populated manually by application code, it can silently go stale "
                    "relative to the row's actual text — search results miss or misrepresent updated content."
                ),
                recommended_direction=(
                    "Convert to a STORED generated column (`GENERATED ALWAYS AS (to_tsvector(...)) STORED`) "
                    "where possible, or add a trigger that recomputes it on INSERT/UPDATE."
                ),
            )
        )
    return findings


def _pg_stat_statements_unavailable_finding(check_slug: str, bullet_summary: str) -> Finding:
    return Finding(
        check_slug=check_slug,
        title=f"Could not assess ({bullet_summary}): pg_stat_statements is not installed",
        severity=Severity.INFORMATIONAL,
        observation=(
            "The pg_stat_statements extension is not installed/enabled on this database, so the actual "
            "SQL text the application runs isn't available to inspect for this bullet."
        ),
        evidence="Checked via pg_extension.",
        business_impact="This aspect of search behavior can't be assessed without pg_stat_statements.",
        recommended_direction=(
            "Enable pg_stat_statements (requires adding it to shared_preload_libraries and a restart, "
            "then CREATE EXTENSION pg_stat_statements) so a future audit can assess this."
        ),
    )


def check_combined_structured_and_freetext_queries(
    conn: psycopg.Connection, config: AuditConfig
) -> list[Finding]:
    """Rubric 04.03 — are structured (JSONB) filters and free-text search combined in the same query?"""
    if not queries.is_pg_stat_statements_available(conn):
        return [_pg_stat_statements_unavailable_finding("combined-structured-and-freetext-queries", "structured + free-text composition")]

    stats = queries.fetch_freetext_and_structured_combination_stats(conn)
    if stats["freetext_statement_count"] == 0 or stats["combined_statement_count"] > 0:
        return []

    return [
        Finding(
            check_slug="combined-structured-and-freetext-queries",
            title="Free-text search and JSONB structured filters appear to be separate query paths",
            severity=Severity.LOW,
            observation=(
                f"pg_stat_statements shows {stats['freetext_statement_count']} observed statement(s) using "
                "free-text search (@@), none of which also use JSONB containment (@>) in the same statement."
            ),
            evidence="Counted via ILIKE pattern matching over pg_stat_statements.query (statements visible to this role only).",
            business_impact=(
                "If structured filtering and free-text search are applied as two separate, un-composed "
                "queries, the application is likely doing extra round-trips or filtering in application "
                "code instead of letting Postgres plan a single combined query."
            ),
            recommended_direction=(
                "Where a search genuinely needs both, express it as one query so the planner can use the "
                "GIN index on the tsvector and any JSONB indexes together."
            ),
        )
    ]


def check_relevance_ranking(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 04.04 — does search relevance ranking (ts_rank or equivalent) exist?"""
    if not queries.is_pg_stat_statements_available(conn):
        return [_pg_stat_statements_unavailable_finding("relevance-ranking", "relevance ranking")]

    stats = queries.fetch_freetext_ranking_stats(conn)
    if stats["freetext_statement_count"] == 0 or stats["ranked_statement_count"] > 0:
        return []

    return [
        Finding(
            check_slug="relevance-ranking",
            title="Free-text search queries found with no relevance ranking",
            severity=Severity.LOW,
            observation=(
                f"pg_stat_statements shows {stats['freetext_statement_count']} observed free-text search "
                "statement(s) (@@), none of which call ts_rank()/ts_rank_cd()."
            ),
            evidence="Counted via ILIKE pattern matching over pg_stat_statements.query (statements visible to this role only).",
            business_impact="Without relevance ranking, search results are likely unordered or arbitrarily ordered.",
            recommended_direction="Add ts_rank()/ts_rank_cd() to order results by relevance where free-text search is used.",
        )
    ]


def check_safe_tsquery_parsing(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 04.05 — is query input handled through websearch_to_tsquery rather than raw to_tsquery?"""
    if not queries.is_pg_stat_statements_available(conn):
        return [_pg_stat_statements_unavailable_finding("safe-tsquery-parsing", "safe tsquery parsing")]

    stats = queries.fetch_raw_tsquery_usage(conn)
    if stats["raw_tsquery_statement_count"] == 0:
        return []

    examples = "; ".join(stats["example_queries"] or [])
    return [
        Finding(
            check_slug="safe-tsquery-parsing",
            title="Raw to_tsquery() usage found without websearch_to_tsquery/plainto_tsquery",
            severity=Severity.MEDIUM,
            observation=(
                f"pg_stat_statements shows {stats['raw_tsquery_statement_count']} observed statement(s) "
                "calling to_tsquery() directly, without going through websearch_to_tsquery() or "
                "plainto_tsquery(). Can't confirm from SQL text alone whether the argument originates "
                "from user-supplied search terms."
            ),
            evidence=f"Example statement(s) (truncated): {examples}" if examples else "See pg_stat_statements.",
            business_impact=(
                "Raw to_tsquery() requires already-valid tsquery syntax (&, |, !, parentheses) — if "
                "user-supplied search terms reach it directly, malformed input (e.g. an unbalanced "
                "operator) raises a hard error instead of degrading gracefully."
            ),
            recommended_direction=(
                "If this argument comes from user input, switch to websearch_to_tsquery() (or "
                "plainto_tsquery() for simpler needs), which parse free-form text safely."
            ),
        )
    ]
