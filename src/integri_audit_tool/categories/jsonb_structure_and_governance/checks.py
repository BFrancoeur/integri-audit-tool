"""Interprets category-2 catalog + sampled-row queries into Finding objects.

One function per rubric checklist bullet (see postgres-database-audit-rubric.md,
"2. JSONB Structure & Governance"). Each takes a live connection + config and
returns zero or more Findings. Kept separate from queries.py so this
interpretation logic is unit-testable against canned row data without a live
database.
"""

from __future__ import annotations

import psycopg

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import Finding, Severity

from . import queries


def is_applicable(conn: psycopg.Connection) -> bool:
    """Category is N/A when the schema has no JSONB columns at all (per rubric guidance)."""
    return len(queries.fetch_jsonb_columns(conn)) > 0


def check_key_naming_drift(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 02.02 — are there inconsistent key names for the same concept?"""
    findings = []
    for col in queries.fetch_jsonb_columns(conn):
        variants = queries.fetch_key_naming_variants(
            conn, col["schema_name"], col["table_name"], col["column_name"]
        )
        for variant in variants:
            findings.append(
                Finding(
                    check_slug="key-naming-drift",
                    title=(
                        f"Inconsistent JSONB key naming in {col['table_name']}.{col['column_name']}: "
                        f"{variant['normalized_key']}"
                    ),
                    severity=Severity.LOW,
                    observation=(
                        f"Column {col['schema_name']}.{col['table_name']}.{col['column_name']} has rows "
                        f"using key variants {variant['observed_keys']} for what appears to be the same "
                        "concept."
                    ),
                    evidence=(
                        f"Sampled up to {queries.SAMPLE_ROW_LIMIT} non-null rows, extracted top-level keys "
                        "via jsonb_object_keys(), grouped case/underscore-insensitively."
                    ),
                    business_impact=(
                        "Application/query code has to account for every variant or it will silently miss "
                        "data written under a different key spelling."
                    ),
                    recommended_direction=(
                        "Standardize on one key name going forward and consider a backfill or a read-time "
                        "normalization layer for historical rows."
                    ),
                )
            )
    return findings


def check_key_type_inconsistency(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 02.03 — are there type inconsistencies for the same key?"""
    findings = []
    for col in queries.fetch_jsonb_columns(conn):
        inconsistencies = queries.fetch_key_type_inconsistencies(
            conn, col["schema_name"], col["table_name"], col["column_name"]
        )
        for row in inconsistencies:
            findings.append(
                Finding(
                    check_slug="key-type-inconsistency",
                    title=(
                        f"Type inconsistency for JSONB key '{row['key_name']}' in "
                        f"{col['table_name']}.{col['column_name']}"
                    ),
                    severity=Severity.MEDIUM,
                    observation=(
                        f"Key '{row['key_name']}' in {col['schema_name']}.{col['table_name']}."
                        f"{col['column_name']} holds values of types {row['observed_types']} across "
                        f"{row['occurrences']} sampled occurrences."
                    ),
                    evidence=(
                        f"Sampled up to {queries.SAMPLE_ROW_LIMIT} non-null rows, typed each value via "
                        "jsonb_typeof()."
                    ),
                    business_impact=(
                        "Query/application code that assumes a single type for this key (e.g. casting to "
                        "numeric) will fail or silently misbehave on rows where it holds a different type."
                    ),
                    recommended_direction=(
                        "Backfill/normalize this key to a single type, and add write-time validation "
                        "(CHECK constraint, trigger, or application-level schema) going forward."
                    ),
                )
            )
    return findings


def check_missing_validation_layer(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 02.04 — is there a validation layer preventing malformed JSONB from being written?"""
    findings = []
    for row in queries.fetch_jsonb_columns_without_validation(conn):
        findings.append(
            Finding(
                check_slug="missing-validation-layer",
                title=f"No validation layer detected for {row['table_name']}.{row['column_name']}",
                severity=Severity.LOW,
                observation=(
                    f"{row['schema_name']}.{row['table_name']}.{row['column_name']} is JSONB with no CHECK "
                    "constraint referencing it and no non-internal trigger on the table."
                ),
                evidence=(
                    "Detected via pg_constraint (CHECK constraints mentioning the column) and pg_trigger "
                    "(heuristic: no user triggers on the table at all)."
                ),
                business_impact=(
                    "Without write-time validation, malformed or inconsistent JSONB is only caught "
                    "downstream (or not at all) rather than rejected at insert/update time."
                ),
                recommended_direction=(
                    "Add a CHECK constraint, trigger, or enforce structure at the application layer for "
                    "this column, backed by a documented key/type registry."
                ),
            )
        )
    return findings
