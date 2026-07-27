"""Interprets Lot & Certification Traceability catalog/row-data queries into
Finding objects.

One function per rubric checklist bullet (see postgres-database-audit-rubric.md,
"13. Lot & Certification Traceability"). Unlike most other categories, these
findings name the *specific* affected lot/serial values (capped at
queries.LOT_SAMPLE_LIMIT, with a total count when truncated) rather than only
a count or percentage — this data is high-stakes for suppliers and their
buyers (Fastener Quality Act lot-traceability requirements and similar), so
"meaningful to the client" means naming names, not just totals. Each takes a
live connection + config and returns zero or more Findings. Kept separate
from queries.py so this interpretation logic is unit-testable against canned
row data without a live database.
"""

from __future__ import annotations

import psycopg

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import Finding, Severity

from . import queries

_HIGH_NULL_FRACTION_THRESHOLD = 0.1
"""Lower than category 6's 0.5 general-purpose threshold — even a modest null
rate on a lot/serial identifier breaks traceability for those specific rows,
so this category flags it sooner."""

_STATS_EVIDENCE_CAVEAT = (
    "From pg_stats (last ANALYZE), an estimate from a sample, not an exhaustive count — a table "
    "that's never been analyzed won't appear here at all."
)


def is_applicable(conn: psycopg.Connection) -> bool:
    """N/A when the schema shows no sign of lot/heat/batch/serial tracking or
    certification data at all — per the rubric's own guidance to skip
    sections that don't apply."""
    return queries.has_lot_or_certification_signal(conn)


def check_lot_columns_poorly_populated(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric bullet 1 — are lot/heat/batch/serial numbers captured consistently?"""
    findings = []
    for row in queries.fetch_lot_shaped_column_null_fractions(conn):
        if row["null_frac"] < _HIGH_NULL_FRACTION_THRESHOLD:
            continue
        findings.append(
            Finding(
                check_slug="lot-columns-poorly-populated",
                title=(
                    f"Lot-tracking column poorly populated: {row['table_name']}.{row['column_name']} "
                    f"({row['null_frac']:.0%} null)"
                ),
                severity=Severity.HIGH,
                observation=(
                    f"Column '{row['column_name']}' on {row['schema_name']}.{row['table_name']} looks "
                    f"like a lot/heat/batch/serial identifier but is ~{row['null_frac']:.0%} null across "
                    f"~{row['n_live_tup']} rows."
                ),
                evidence=_STATS_EVIDENCE_CAVEAT,
                business_impact=(
                    "A missing lot/serial number breaks traceability at the source for that row — there's "
                    "no way to link it back to a certification record at all, regardless of how well-linked "
                    "the rest of the data is."
                ),
                recommended_direction=(
                    "Confirm whether this column should be required for all rows; if so, add a NOT NULL "
                    "constraint and backfill where derivable."
                ),
            )
        )
    return findings


def check_orphaned_lot_certification_links(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric bullet 2 — is there a verifiable, non-orphaned link between a lot/serial
    number and its certification record?"""
    findings = []
    for table in queries.fetch_lot_tables_with_unconstrained_cert_link(conn):
        sample = queries.fetch_lots_with_unlinked_certification(
            conn, table["schema_name"], table["table_name"], table["lot_column"], table["link_column"]
        )
        if not sample:
            continue
        total = sample[0]["total_unlinked"]
        lot_values = [str(row["lot_value"]) for row in sample]
        shown_note = f" (showing {len(lot_values)} of {total})" if total > len(lot_values) else ""
        findings.append(
            Finding(
                check_slug="orphaned-lot-certification-links",
                title=f"Orphaned lot-to-certification links: {table['table_name']} ({total} affected)",
                severity=Severity.HIGH,
                observation=(
                    f"{total} row(s) in {table['schema_name']}.{table['table_name']} have no certification "
                    f"link ('{table['link_column']}' is null, and no FOREIGN KEY constraint enforces it). "
                    f"Affected lot numbers{shown_note}: {', '.join(lot_values)}."
                ),
                evidence=(
                    "Detected via information_schema.columns naming heuristic, plus a sample of rows "
                    f"where the link column is null (up to {queries.LOT_SAMPLE_LIMIT})."
                ),
                business_impact=(
                    "Each of these lots has no verifiable link to its certification record — for regulated/"
                    "traceability-required parts (Fastener Quality Act and similar), this is a compliance "
                    "and contract-loss exposure, not just a data-quality nit."
                ),
                recommended_direction=(
                    "Investigate these specific lot numbers first; add a FOREIGN KEY constraint on the "
                    "link column once historical gaps are resolved so this can't recur silently."
                ),
            )
        )
    return findings


def check_duplicate_lot_numbers(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric bullet 3 — are lot/serial numbers unique where uniqueness is required?"""
    findings = []
    for table in queries.fetch_lot_columns_without_unique_constraint(conn):
        duplicates = queries.fetch_duplicate_lot_values(
            conn, table["schema_name"], table["table_name"], table["lot_column"]
        )
        if not duplicates:
            continue
        examples = ", ".join(f"{row['lot_value']} (x{row['occurrence_count']})" for row in duplicates)
        findings.append(
            Finding(
                check_slug="duplicate-lot-numbers",
                title=(
                    f"Duplicate lot numbers: {table['table_name']}.{table['lot_column']} "
                    f"({len(duplicates)} reused)"
                ),
                severity=Severity.HIGH,
                observation=(
                    f"{len(duplicates)} lot number(s) in {table['schema_name']}.{table['table_name']}."
                    f"{table['lot_column']} appear more than once, with no unique constraint preventing "
                    f"it. Examples: {examples}."
                ),
                evidence=(
                    "Detected via GROUP BY/HAVING COUNT(*) > 1 on the lot column, plus absence of a "
                    "matching unique index."
                ),
                business_impact=(
                    "A reused lot number means the same identifier could point to two different physical "
                    "batches — anyone tracing a lot back to its certification risks pulling the wrong "
                    "certificate entirely."
                ),
                recommended_direction=(
                    "Investigate whether these are true duplicates (data entry error, failed merge dedup) "
                    "or legitimately distinct batches sharing a number; add a UNIQUE constraint once resolved."
                ),
            )
        )
    return findings


def check_ungoverned_certification_data(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric bullet 4 — is certification data governed, or crammed into ungoverned JSONB?"""
    findings = []
    for row in queries.fetch_cert_jsonb_columns_without_validation(conn):
        findings.append(
            Finding(
                check_slug="ungoverned-certification-data",
                title=f"Ungoverned certification data: {row['table_name']}.{row['column_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"{row['schema_name']}.{row['table_name']}.{row['column_name']} is JSONB, holds what "
                    "looks like certification data by name, and has no CHECK constraint or trigger "
                    "validating it."
                ),
                evidence=(
                    "Detected via pg_constraint (CHECK constraints mentioning the column) and pg_trigger "
                    "(heuristic: no user triggers on the table at all)."
                ),
                business_impact=(
                    "Without write-time validation, malformed or incomplete certification data is only "
                    "caught downstream (or not at all), undermining the traceability this category exists "
                    "to verify."
                ),
                recommended_direction=(
                    "Add a CHECK constraint, trigger, or application-layer schema enforcing the expected "
                    "certification fields (cert number, issue date, material spec) for this column."
                ),
            )
        )
    return findings
