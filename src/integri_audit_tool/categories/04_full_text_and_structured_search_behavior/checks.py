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

_CATEGORY_NUMBER = 4
_CATEGORY_NAME = "Full-Text & Structured Search Behavior"


def is_applicable(conn: psycopg.Connection) -> bool:
    """Category is N/A when the schema has no tsvector columns at all (per rubric guidance)."""
    return len(queries.fetch_tsvector_columns(conn)) > 0


def check_missing_fulltext_index(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 04.01 — is full-text search using tsvector/tsquery with GIN indexing?"""
    findings = []
    for row in queries.fetch_tsvector_columns_without_fulltext_index(conn):
        findings.append(
            Finding(
                category_number=_CATEGORY_NUMBER,
                category_name=_CATEGORY_NAME,
                check_id="04.01",
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
                category_number=_CATEGORY_NUMBER,
                category_name=_CATEGORY_NAME,
                check_id="04.02",
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
