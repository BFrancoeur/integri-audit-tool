"""Interprets category-6 planner-statistics/catalog queries into Finding objects.

One function per rubric checklist bullet (see postgres-database-audit-rubric.md,
"6. Data Quality & Integrity") that's actually assessable from read-only
catalog/statistics access. Each takes a live connection + config and returns
zero or more Findings. Kept separate from queries.py so this interpretation
logic is unit-testable against canned row data without a live database.
"""

from __future__ import annotations

import psycopg

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import Finding, Severity

from . import queries

_CATEGORY_NUMBER = 6
_CATEGORY_NAME = "Data Quality & Integrity"

_HIGH_NULL_FRACTION_THRESHOLD = 0.5
_NEAR_UNIQUE_RATIO_THRESHOLD = 0.98

_STATS_EVIDENCE_CAVEAT = (
    "From pg_stats (last ANALYZE), an estimate from a sample, not an exhaustive count — a table "
    "that's never been analyzed won't appear here at all."
)


def check_high_null_fraction_columns(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 06.01 — what percentage of rows have null values in fields expected to be populated?"""
    findings = []
    for row in queries.fetch_nullable_column_null_fractions(conn):
        if row["null_frac"] < _HIGH_NULL_FRACTION_THRESHOLD:
            continue
        findings.append(
            Finding(
                category_number=_CATEGORY_NUMBER,
                category_name=_CATEGORY_NAME,
                check_id="06.01",
                title=f"High null rate: {row['table_name']}.{row['column_name']} ({row['null_frac']:.0%} null)",
                severity=Severity.INFORMATIONAL,
                observation=(
                    f"Column '{row['column_name']}' on {row['schema_name']}.{row['table_name']} is "
                    f"nullable and ~{row['null_frac']:.0%} of its ~{row['n_live_tup']} rows are null."
                ),
                evidence=_STATS_EVIDENCE_CAVEAT,
                business_impact=(
                    "A high null rate isn't inherently wrong (many columns are legitimately optional), "
                    "but if this field is expected to be populated, it points at either a data entry gap "
                    "or a backfill that never ran."
                ),
                recommended_direction=(
                    "Confirm with the schema owner whether this column should be populated for all/most "
                    "rows; if so, investigate the write path for missing population."
                ),
            )
        )
    return findings


def check_unvalidated_foreign_keys(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 06.03 — are there orphaned foreign key references / missing referential integrity?"""
    findings = []
    for row in queries.fetch_unvalidated_foreign_keys(conn):
        findings.append(
            Finding(
                category_number=_CATEGORY_NUMBER,
                category_name=_CATEGORY_NAME,
                check_id="06.03",
                title=f"Unvalidated foreign key: {row['conname']} on {row['table_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"Constraint '{row['conname']}' on {row['schema_name']}.{row['table_name']} "
                    f"({row['constraint_def']}) was created NOT VALID and has never been validated. "
                    "Postgres enforces it for new writes but hasn't confirmed existing rows satisfy it."
                ),
                evidence="Detected via pg_constraint.convalidated = false.",
                business_impact=(
                    "Rows written before the constraint existed (or during the NOT VALID window) may "
                    "already violate it — orphaned references sitting undetected in the table."
                ),
                recommended_direction="Run VALIDATE CONSTRAINT (does not block concurrent writes) to confirm or surface violations.",
            )
        )
    return findings


def check_near_unique_columns_without_constraint(
    conn: psycopg.Connection, config: AuditConfig
) -> list[Finding]:
    """Rubric 06.04 — are there duplicate records that should be unique (missing unique constraints)?"""
    findings = []
    for row in queries.fetch_columns_without_unique_constraint(conn):
        ratio = _distinct_ratio(row["n_distinct"], row["n_live_tup"])
        if ratio is None or ratio < _NEAR_UNIQUE_RATIO_THRESHOLD:
            continue
        findings.append(
            Finding(
                category_number=_CATEGORY_NUMBER,
                category_name=_CATEGORY_NAME,
                check_id="06.04",
                title=f"Near-unique column without a unique constraint: {row['table_name']}.{row['column_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"Column '{row['column_name']}' on {row['schema_name']}.{row['table_name']} is "
                    f"~{ratio:.0%} distinct across ~{row['n_live_tup']} rows but has no unique constraint "
                    "or index covering it alone."
                ),
                evidence=_STATS_EVIDENCE_CAVEAT,
                business_impact=(
                    "Values are behaviorally unique today but nothing stops a future write from "
                    "duplicating one — small drift now becomes a real data-quality incident once "
                    "something (a join, a lookup) assumes uniqueness that was never enforced."
                ),
                recommended_direction=(
                    "If this column is meant to be unique (e.g. email, slug, external ID), add a UNIQUE "
                    "constraint or index; if duplicates already exist, they'll need resolving first."
                ),
            )
        )
    return findings


def check_never_null_nullable_columns(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 06.05 — discrepancy between what the schema allows and what the data contains?"""
    findings = []
    for row in queries.fetch_nullable_column_null_fractions(conn):
        if row["null_frac"] != 0:
            continue
        findings.append(
            Finding(
                category_number=_CATEGORY_NUMBER,
                category_name=_CATEGORY_NAME,
                check_id="06.05",
                title=f"Nullable column never actually null: {row['table_name']}.{row['column_name']}",
                severity=Severity.LOW,
                observation=(
                    f"Column '{row['column_name']}' on {row['schema_name']}.{row['table_name']} allows "
                    f"NULL but has none across ~{row['n_live_tup']} rows."
                ),
                evidence=_STATS_EVIDENCE_CAVEAT,
                business_impact=(
                    "The schema is looser than actual usage — not a defect by itself, but it means the "
                    "database isn't enforcing a rule the data already follows, so nothing prevents a "
                    "future write from introducing the first null."
                ),
                recommended_direction="If this column should always be populated, add a NOT NULL constraint to make the existing behavior enforced rather than incidental.",
            )
        )
    return findings


def check_audit_timestamp_columns_have_nulls(
    conn: psycopg.Connection, config: AuditConfig
) -> list[Finding]:
    """Rubric 06.06 — are timestamp/audit columns consistently populated and reliable for change tracking?"""
    findings = []
    for row in queries.fetch_audit_timestamp_column_null_fractions(conn):
        findings.append(
            Finding(
                category_number=_CATEGORY_NUMBER,
                category_name=_CATEGORY_NAME,
                check_id="06.06",
                title=f"Audit timestamp column has nulls: {row['table_name']}.{row['column_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"Column '{row['column_name']}' on {row['schema_name']}.{row['table_name']} looks "
                    f"like an audit/change-tracking timestamp but is ~{row['null_frac']:.0%} null across "
                    f"~{row['n_live_tup']} rows."
                ),
                evidence=_STATS_EVIDENCE_CAVEAT + " Matched by name (created_at/updated_at/modified_at).",
                business_impact=(
                    "Gaps in created_at/updated_at undermine anything relying on them for change "
                    "tracking, auditing, or incremental sync (CDC, cache invalidation, 'what changed since X')."
                ),
                recommended_direction=(
                    "Backfill missing values where derivable, and default/trigger this column going "
                    "forward so every row gets one."
                ),
            )
        )
    return findings


def _distinct_ratio(n_distinct: float, n_live_tup: int) -> float | None:
    if n_live_tup <= 0:
        return None
    if n_distinct < 0:
        return min(-n_distinct, 1.0)
    return min(n_distinct / n_live_tup, 1.0)
