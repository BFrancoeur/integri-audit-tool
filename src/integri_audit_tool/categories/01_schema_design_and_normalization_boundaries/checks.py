"""Interprets category-1 catalog queries into Finding objects.

One function per rubric checklist bullet (see postgres-database-audit-rubric.md,
"1. Schema Design & Normalization Boundaries"). Each takes a live connection +
config and returns zero or more Findings. Kept separate from queries.py so this
interpretation logic is unit-testable against canned row data without a live
database.
"""

from __future__ import annotations

import psycopg

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import Finding, Severity

from . import queries

_INTEGER_FAMILY = {"integer", "bigint", "smallint"}


def check_missing_foreign_keys(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 01.04 — are FK constraints present where relationships exist?"""
    findings = []
    for row in queries.fetch_fk_like_columns_without_fk(conn):
        findings.append(
            Finding(
                check_slug="missing-foreign-keys",
                title=f"FK-shaped column without a declared constraint: {row['table_name']}.{row['column_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"Column '{row['column_name']}' ({row['data_type']}) on "
                    f"{row['schema_name']}.{row['table_name']} looks like a foreign key reference "
                    "(name ends in '_id') but has no declared FOREIGN KEY constraint."
                ),
                evidence="Detected via information_schema.columns + table_constraints (naming heuristic).",
                business_impact=(
                    "Without a declared constraint, referential integrity depends entirely on "
                    "application code — orphaned or inconsistent references can accumulate silently."
                ),
                recommended_direction=(
                    "If this column does reference another table, add a FOREIGN KEY constraint "
                    "(or confirm intentionally denormalized / soft-referenced and document why)."
                ),
            )
        )
    return findings


def check_schema_drift(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 01.05 — is there evidence of schema drift (same concept, different naming/types)?"""
    findings = []
    for row in queries.fetch_columns_with_name_or_type_drift(conn):
        type_drift = len(row["observed_types"]) > 1
        severity = Severity.MEDIUM if type_drift else Severity.LOW
        kind = "naming and type" if type_drift else "naming"
        findings.append(
            Finding(
                check_slug="schema-drift",
                title=f"Schema drift ({kind}) for column concept '{row['normalized_name']}'",
                severity=severity,
                observation=(
                    f"The concept '{row['normalized_name']}' appears with names "
                    f"{row['observed_names']} and types {row['observed_types']} across tables "
                    f"{row['tables']}."
                ),
                evidence="Grouped via information_schema.columns on lower(column_name) with underscores stripped.",
                business_impact=(
                    "Inconsistent types for the same concept can cause silent bugs in joins/comparisons; "
                    "inconsistent naming increases onboarding cost and the chance of missed references."
                ),
                recommended_direction=(
                    "Standardize on one name and type for this concept, or document why the variants "
                    "are intentionally different."
                ),
            )
        )
    return findings


def check_primary_key_consistency(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 01.06 — are primary keys/identity columns used consistently?"""
    findings = []

    for row in queries.fetch_tables_without_primary_key(conn):
        findings.append(
            Finding(
                check_slug="primary-key-consistency",
                title=f"Table without a primary key: {row['table_name']}",
                severity=Severity.HIGH,
                observation=f"{row['schema_name']}.{row['table_name']} has no PRIMARY KEY constraint.",
                evidence="Detected via information_schema.table_constraints.",
                business_impact=(
                    "Without a primary key, rows can't be reliably deduplicated or referenced, and "
                    "many replication/CDC tools either can't operate on the table or silently degrade."
                ),
                recommended_direction="Add a primary key (surrogate or natural) unless this table is deliberately append-only/unkeyed.",
            )
        )

    pk_rows = queries.fetch_primary_key_column_types(conn)
    families = {row["data_type"]: _classify_pk_type(row["data_type"]) for row in pk_rows}
    observed_families = set(families.values())
    if len(observed_families) > 1:
        by_family: dict[str, list[str]] = {}
        for row in pk_rows:
            family = _classify_pk_type(row["data_type"])
            by_family.setdefault(family, []).append(f"{row['table_name']} ({row['data_type']})")
        summary = "; ".join(f"{family}: {', '.join(tables)}" for family, tables in sorted(by_family.items()))
        findings.append(
            Finding(
                check_slug="primary-key-consistency",
                title="Mixed primary key type families across the schema",
                severity=Severity.INFORMATIONAL,
                observation=f"Primary keys use more than one type family: {summary}.",
                evidence="Detected via information_schema.table_constraints + key_column_usage.",
                business_impact=(
                    "Mixing UUID and integer/serial primary keys isn't necessarily wrong, but ad hoc "
                    "mixing without a stated reason makes join/FK typing less predictable across the schema."
                ),
                recommended_direction="Confirm the mix is a deliberate choice (e.g. UUID for public-facing entities, serial elsewhere) and document it.",
            )
        )

    return findings


def _classify_pk_type(data_type: str) -> str:
    if data_type == "uuid":
        return "uuid"
    if data_type in _INTEGER_FAMILY:
        return "integer"
    return "other"
