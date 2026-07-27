"""Interprets category-3 catalog queries into Finding objects.

One function per rubric checklist bullet (see postgres-database-audit-rubric.md,
"3. Indexing Strategy"). Each takes a live connection + config and returns zero
or more Findings. Kept separate from queries.py so this interpretation logic is
unit-testable against canned row data without a live database.
"""

from __future__ import annotations

import psycopg

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import Finding, Severity

from . import queries


def check_unused_indexes(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 03.01 — do query patterns match the indexes that exist?"""
    findings = []
    for row in queries.fetch_unused_indexes(conn):
        findings.append(
            Finding(
                check_slug="unused-indexes",
                title=f"Unused index: {row['index_name']} on {row['table_name']}",
                severity=Severity.LOW,
                observation=(
                    f"Index '{row['index_name']}' on {row['schema_name']}.{row['table_name']} "
                    "has recorded zero scans and is not backing a primary key or unique constraint."
                ),
                evidence=f"idx_scan=0, index size={row['index_size_bytes']} bytes (pg_stat_user_indexes).",
                business_impact=(
                    "Unused indexes add write overhead on every INSERT/UPDATE/DELETE to the table "
                    "and consume storage without providing any read benefit."
                ),
                recommended_direction=(
                    "Confirm the index isn't used by infrequent batch/reporting queries "
                    "(check over a full reporting cycle, not just recent activity), then drop it."
                ),
            )
        )
    return findings


def check_gin_usage(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 03.02 — is GIN used appropriately for JSONB containment / full-text search?"""
    findings = []
    for row in queries.fetch_jsonb_columns_without_gin(conn):
        findings.append(
            Finding(
                check_slug="gin-usage",
                title=f"JSONB column without a GIN index: {row['table_name']}.{row['column_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"Column '{row['column_name']}' on {row['schema_name']}.{row['table_name']} is "
                    "JSONB but no GIN index was found covering it."
                ),
                evidence="Detected via information_schema.columns + pg_indexes (heuristic text match on indexdef).",
                business_impact=(
                    "Containment (@>) or key-existence queries against this column will require a "
                    "sequential scan, which won't scale as the table grows."
                ),
                recommended_direction=(
                    "If this column is queried with @> or key-existence operators, add a GIN index "
                    "(jsonb_path_ops for containment-only, default jsonb_ops if key-existence queries are needed)."
                ),
            )
        )
    return findings


def check_redundant_indexes(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 03.04 — are there redundant or overlapping indexes?"""
    findings = []
    for row in queries.fetch_indexes_sharing_leading_column(conn):
        index_list = ", ".join(row["index_names"])
        findings.append(
            Finding(
                check_slug="redundant-indexes",
                title=f"Possible overlapping indexes on {row['table_name']} ({row['leading_column']})",
                severity=Severity.LOW,
                observation=(
                    f"{len(row['index_names'])} indexes on {row['table_name']} share the same leading "
                    f"column '{row['leading_column']}': {index_list}."
                ),
                evidence="; ".join(row["index_defs"]),
                business_impact=(
                    "Overlapping indexes are maintained redundantly on every write without adding "
                    "distinct query coverage, increasing write amplification and storage cost."
                ),
                recommended_direction=(
                    "Review whether one index's columns are a strict subset of another's; if so, "
                    "the narrower index is usually safe to drop."
                ),
            )
        )
    return findings
