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

_HIGH_NULL_FRACTION_THRESHOLD = 0.5
_NEAR_UNIQUE_RATIO_THRESHOLD = 0.98

_NEAR_ZERO_NULL_FRACTION_THRESHOLD = 0.01
"""Above this, a column no longer counts as "effectively always populated" for
06.05's NOT-NULL-constraint-coverage signal -- loosened from a strict-zero
check (SOP-driven, 2026-08-03) since a handful of legacy/exceptional null
rows shouldn't disqualify an otherwise-required column from this finding."""

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
                check_slug="high-null-fraction-columns",
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
                check_slug="unvalidated-foreign-keys",
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
                check_slug="near-unique-columns-without-constraint",
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
        if row["null_frac"] > _NEAR_ZERO_NULL_FRACTION_THRESHOLD:
            continue
        findings.append(
            Finding(
                check_slug="never-null-nullable-columns",
                title=f"Nullable column effectively always populated: {row['table_name']}.{row['column_name']}",
                severity=Severity.LOW,
                observation=(
                    f"Column '{row['column_name']}' on {row['schema_name']}.{row['table_name']} allows "
                    f"NULL but is null in only ~{row['null_frac']:.1%} of ~{row['n_live_tup']} rows."
                ),
                evidence=_STATS_EVIDENCE_CAVEAT,
                business_impact=(
                    "The schema is looser than actual usage — not a defect by itself, but it means the "
                    "database isn't enforcing a rule the data already follows, so nothing prevents a "
                    "future write from introducing more nulls than the handful (if any) seen so far."
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
                check_slug="audit-timestamp-columns-have-nulls",
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


def check_low_cardinality_ungoverned_columns(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 06.07 — is there CHECK-constraint or lookup-table coverage for
    low-cardinality text columns (missing CHECK coverage merged with
    orphaned/inconsistent enum-like free-text — the same underlying signal)?
    """
    findings = []
    for row in queries.fetch_low_cardinality_ungoverned_columns(conn):
        findings.append(
            Finding(
                check_slug="low-cardinality-ungoverned-columns",
                title=f"Ungoverned low-cardinality column: {row['table_name']}.{row['column_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"Column '{row['column_name']}' on {row['schema_name']}.{row['table_name']} has "
                    f"only ~{row['n_distinct']:.0f} distinct values across ~{row['n_live_tup']} rows, "
                    "consistent with an enum/status field, but has no CHECK constraint and no foreign "
                    "key to a lookup table."
                ),
                evidence=_STATS_EVIDENCE_CAVEAT,
                business_impact=(
                    "Without a CHECK constraint or lookup-table FK, nothing stops the value set from "
                    "drifting silently over time (e.g. 'GOOD'/'good'/'Good'/'OK' all meaning the same "
                    "thing) — a classic source of application bugs in anything that switches on this value."
                ),
                recommended_direction=(
                    "Add a CHECK constraint enumerating the valid values, convert the column to an ENUM "
                    "type, or normalize it into a lookup table with a foreign key."
                ),
            )
        )
    return findings


def check_missing_default_on_status_like_columns(
    conn: psycopg.Connection, config: AuditConfig
) -> list[Finding]:
    """Rubric 06.08 — are status/flag-shaped NOT NULL columns relying on the
    application layer to supply a default instead of a database DEFAULT?
    """
    findings = []
    for row in queries.fetch_missing_default_on_status_like_columns(conn):
        findings.append(
            Finding(
                check_slug="missing-default-on-status-like-columns",
                title=f"No database default on a required status-like column: {row['table_name']}.{row['column_name']}",
                severity=Severity.LOW,
                observation=(
                    f"Column '{row['column_name']}' ({row['data_type']}) on "
                    f"{row['schema_name']}.{row['table_name']} is NOT NULL with no DEFAULT — every "
                    "insert must explicitly supply a value."
                ),
                evidence="Detected via information_schema.columns (is_nullable = 'NO', column_default IS NULL).",
                business_impact=(
                    "If more than one code path writes to this table (multiple services, an admin "
                    "script, a migration backfill), each one has to independently remember what this "
                    "column should default to — a consistency risk a database-level DEFAULT removes entirely."
                ),
                recommended_direction="Add a DEFAULT at the database level for this column's normal/starting state.",
            )
        )
    return findings


def check_orphaned_rows_on_unvalidated_foreign_keys(
    conn: psycopg.Connection, config: AuditConfig
) -> list[Finding]:
    """Rubric 06.09 — sampling actual rows: do any already violate a declared
    (but unvalidated) foreign key relationship?
    """
    findings = []
    for row in queries.fetch_unvalidated_fk_detail(conn):
        orphaned_values = queries.fetch_orphaned_child_rows(
            conn,
            row["schema_name"],
            row["table_name"],
            row["child_column"],
            row["parent_schema"],
            row["parent_table"],
            row["parent_column"],
        )
        if not orphaned_values:
            continue
        at_least = len(orphaned_values) >= queries.ORPHAN_SAMPLE_LIMIT
        count_phrase = f"at least {len(orphaned_values)}" if at_least else str(len(orphaned_values))
        findings.append(
            Finding(
                check_slug="orphaned-rows-on-unvalidated-foreign-keys",
                title=f"Orphaned rows found: {row['table_name']}.{row['child_column']}",
                severity=Severity.HIGH,
                observation=(
                    f"Sampling found {count_phrase} row(s) in {row['schema_name']}.{row['table_name']} "
                    f"whose '{row['child_column']}' value has no matching row in "
                    f"{row['parent_schema']}.{row['parent_table']}.{row['parent_column']} — constraint "
                    f"'{row['conname']}' was created NOT VALID and never validated. "
                    f"Example value(s): {orphaned_values[:5]}"
                ),
                evidence=f"Sampled up to {queries.ORPHAN_SAMPLE_LIMIT} child rows via an anti-join against the parent table, not a full scan.",
                business_impact=(
                    "These rows already violate referential integrity today — any code that assumes "
                    "the foreign key holds (a join, a lookup) can silently drop or mishandle them."
                ),
                recommended_direction=(
                    "Resolve the orphaned rows (fix, reassign, or delete them), then run VALIDATE "
                    "CONSTRAINT to confirm and start enforcing the relationship fully."
                ),
            )
        )
    return findings


def check_malformed_jsonb_entries(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 06.02 — are there malformed JSONB entries (wrong types, unexpected
    nesting, empty objects where data was expected)? Scoped to the empty-
    document symptom specifically; see queries.py's comment on why the other
    symptoms are already covered by category 2's key-type-inconsistency check.
    """
    findings = []
    for col in queries.fetch_jsonb_columns(conn):
        stats = queries.fetch_empty_jsonb_document_stats(
            conn, col["schema_name"], col["table_name"], col["column_name"]
        )
        if stats["sample_size"] < queries.MIN_JSONB_SAMPLE_SIZE_FOR_EMPTY_CHECK or stats["empty_count"] == 0:
            continue
        empty_fraction = stats["empty_count"] / stats["sample_size"]
        if empty_fraction < queries.MIN_EMPTY_JSONB_FRACTION_TO_FLAG:
            continue
        findings.append(
            Finding(
                check_slug="malformed-jsonb-entries",
                title=f"Empty JSONB documents: {col['table_name']}.{col['column_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"{stats['empty_count']} of {stats['sample_size']} sampled non-null rows "
                    f"(~{empty_fraction:.1%}) in {col['schema_name']}.{col['table_name']}."
                    f"{col['column_name']} hold an empty '{{}}' or '[]' document."
                ),
                evidence=(
                    f"Sampled up to {queries.JSONB_SAMPLE_ROW_LIMIT} non-null rows, counted documents "
                    "equal to an empty object or array."
                ),
                business_impact=(
                    "A non-null but empty JSONB document usually means the write path never actually "
                    "populated this field — code that reads it downstream sees 'present but empty' "
                    "rather than a clear absence, which is easy to mishandle."
                ),
                recommended_direction=(
                    "Trace the write path that produces empty documents (a form step that's skippable, "
                    "a serialization bug); consider whether these rows should be NULL instead."
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
