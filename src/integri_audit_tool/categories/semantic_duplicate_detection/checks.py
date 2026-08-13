"""Interprets Semantic Duplicate Detection queries into Finding objects.

Two checks, deliberately treated differently:
- Exact-match (fingerprint equality) ships confirmed findings directly —
  the fingerprint rule itself was already human-approved when the
  engagement's config was authored, so an exact match under that rule
  doesn't need a second per-finding confirmation.
- Fuzzy-match (pg_trgm similarity) ships each candidate with
  requires_attestation=True, and its Check is marked interactive=True —
  per attestation.py/runner.py's design, the human reviews each candidate
  after this check's own (fast) query work has already closed its
  transaction, never while a transaction is open. A non-interactive run
  ships candidates unconfirmed, clearly marked in the report rather than
  silently dropped or silently confirmed.
"""

from __future__ import annotations

import psycopg

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.fingerprint_config import load_fingerprint_config
from integri_audit_tool.models import Finding, Severity

from . import queries


def check_exact_match_duplicates(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Semantic Duplicate Detection 1 — do any rows share an identical
    normalized identity fingerprint (the same real-world product, entered
    more than once)?
    """
    fp_config = load_fingerprint_config(config.duplicate_fingerprint_config)
    field_summary = ", ".join(f"{f.column} ({'+'.join(f.normalize) or 'as-is'})" for f in fp_config.fields)

    findings = []
    for row in queries.fetch_exact_match_duplicates(conn, fp_config):
        findings.append(
            Finding(
                check_slug="exact-match-duplicates",
                title=f"{row['match_count']} rows share an identical fingerprint",
                severity=Severity.MEDIUM,
                observation=(
                    f"{row['match_count']} rows in {fp_config.schema}.{fp_config.table} "
                    f"(ids: {row['matching_ids']}) normalize to the identical fingerprint "
                    f"'{row['fingerprint']}' under the configured identity rule."
                ),
                evidence=f"Exact match on the normalized fingerprint built from: {field_summary}.",
                business_impact=(
                    "Records that are the same real-world entity but technically unique rows "
                    "(different primary key, different SKU) fragment inventory, reporting, and "
                    "reorder logic — each duplicate is counted separately by anything that doesn't "
                    "know they're the same thing."
                ),
                recommended_direction="Confirm these are true duplicates, then merge or link them to a single canonical record.",
            )
        )
    return findings


def check_fuzzy_match_duplicates(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Semantic Duplicate Detection 2 — do any rows look like the same
    real-world product despite non-identical formatting (near-duplicates)?
    Each candidate requires human confirmation before it's a real finding.
    """
    if not queries.is_pg_trgm_available(conn):
        return [
            Finding(
                check_slug="fuzzy-match-duplicates",
                title="Could not assess fuzzy-match duplicates: pg_trgm is not installed",
                severity=Severity.INFORMATIONAL,
                observation="The pg_trgm extension is not installed/enabled on this database.",
                evidence="Checked via pg_extension.",
                business_impact="Near-duplicate (non-identical) records can't be detected without pg_trgm.",
                recommended_direction="Install the pg_trgm extension (no shared_preload_libraries entry needed) so a future audit can assess this.",
            )
        ]

    fp_config = load_fingerprint_config(config.duplicate_fingerprint_config)
    findings = []
    for row in queries.fetch_fuzzy_match_candidates(conn, fp_config):
        findings.append(
            Finding(
                check_slug="fuzzy-match-duplicates",
                title=f"Possible duplicate: '{row['fingerprint_a']}' / '{row['fingerprint_b']}'",
                severity=Severity.MEDIUM,
                observation=(
                    f"Two distinct fingerprints in {fp_config.schema}.{fp_config.table} are "
                    f"{row['sim']:.0%} similar (trigram similarity): '{row['fingerprint_a']}' and "
                    f"'{row['fingerprint_b']}'."
                ),
                evidence=(
                    f"pg_trgm similarity() >= {fp_config.similarity_threshold} — a statistical text-"
                    "similarity signal, not a confirmed match; false positives are expected, which is "
                    "why this finding requires human confirmation before it's reported as real."
                ),
                business_impact=(
                    "If these are the same real-world product recorded inconsistently (a typo, a "
                    "unit-format difference, an abbreviation), they fragment inventory and reporting "
                    "the same way an exact duplicate would — just less visibly, since nothing "
                    "currently matches them."
                ),
                recommended_direction="Review both records; if they're the same entity, merge or link them.",
                requires_attestation=True,
            )
        )
    return findings
