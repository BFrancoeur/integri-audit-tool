"""Rubric category 13: Lot & Certification Traceability.

New category, not present in the original 11-category build — nothing else in
this rubric asks about lot/heat/batch/serial traceability tied to
certification records (Fastener Quality Act and similar regulated-industry
requirements). All 4 of its checklist bullets are implemented, each reusing
an already-proven heuristic mechanism from an existing category, re-scoped to
lot/cert-shaped naming: bullet 1 mirrors category 6's null-fraction approach,
bullet 2 mirrors category 1's FK-shaped-column heuristic, bullet 3 mirrors
category 6's near-unique-column heuristic (done as an exact GROUP BY here,
not a pg_stats estimate, so specific duplicate values can be named), and
bullet 4 mirrors category 2's JSONB-validation heuristic.

Uses `applicability`: a database with no lot/heat/batch/serial-shaped columns
and no cert-shaped tables/columns at all makes this whole category N/A,
same pattern as category 2/4's JSONB/full-text applicability checks.

`out_of_scope`: confirming a certificate is authentic or that the underlying
physical material matches what it claims requires reading the document
itself, not just verifying a DB record exists — outside what a read-only
connection can determine.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    slug="lot-and-certification-traceability",
    name="Lot & Certification Traceability",
    applicability=checks.is_applicable,
    checks=[
        Check(
            slug="lot-columns-poorly-populated",
            rubric_bullet=1,
            description="Are lot/heat/batch/serial numbers captured consistently on relevant records?",
            fn=checks.check_lot_columns_poorly_populated,
        ),
        Check(
            slug="orphaned-lot-certification-links",
            rubric_bullet=2,
            description="Is there a verifiable, non-orphaned link between a lot/serial number and its certification record?",
            fn=checks.check_orphaned_lot_certification_links,
        ),
        Check(
            slug="duplicate-lot-numbers",
            rubric_bullet=3,
            description="Are lot/serial numbers unique where uniqueness is required?",
            fn=checks.check_duplicate_lot_numbers,
        ),
        Check(
            slug="ungoverned-certification-data",
            rubric_bullet=4,
            description="Is certification data governed, or crammed into ungoverned free text/JSONB?",
            fn=checks.check_ungoverned_certification_data,
        ),
    ],
    out_of_scope=[
        "Lot & Certification Traceability — confirming a certificate is authentic or that the underlying physical "
        "material actually matches what the certificate claims requires reading the document "
        "itself, not just verifying a DB record referencing it exists — outside what a read-only "
        "database connection can determine.",
    ],
)
