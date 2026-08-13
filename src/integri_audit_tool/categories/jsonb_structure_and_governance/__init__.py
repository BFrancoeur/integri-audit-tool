"""Rubric category 2: JSONB Structure & Governance.

4 of the rubric's 6 checklist bullets are implemented (02.02, 02.03, 02.04, 02.06).

02.01 (a governing schema/registry for JSONB keys) is not follow-up work for
*this* category — it's superseded by category 11's 11.03, which closes this
exact loop from the institutional-knowledge angle (same underlying signal: a
heuristically-named registry table).

**Added (2026-08-08):** 02.06 (`orphaned-legacy-keys`, orphaned/legacy keys
accumulating from deprecated features) — a statistical-rarity heuristic, the
same shape as category 6's 06.01/06.05 `null_frac` approach, applied to key
*presence* within a sampled JSONB column instead of column nullness. Flags a
top-level key that occurs in only a small fraction of sampled non-null rows;
doesn't distinguish a genuinely abandoned key from a legitimately sparse but
still-current one, so it's capped at LOW severity and framed for
confirmation with the application team, not as a proven finding.

02.05 (nesting depth / brittle query paths) is declared via `out_of_scope`,
not deferred: the brittleness lives in application query code, not in the
database — a read-only connection has no visibility into how the application
constructs its queries.

This is the first category to use `applicability` — per the rubric's own
guidance ("skip full-text search section entirely if none exists"), a
database with no JSONB columns at all makes this whole category N/A rather
than a clean pass.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    slug="jsonb-structure-and-governance",
    name="JSONB Structure & Governance",
    applicability=checks.is_applicable,
    checks=[
        Check(
            slug="key-naming-drift",
            rubric_bullet=2,
            description="Are there inconsistent key names for the same concept (diameter vs dia vs diameter_in)?",
            fn=checks.check_key_naming_drift,
        ),
        Check(
            slug="key-type-inconsistency",
            rubric_bullet=3,
            description="Are there type inconsistencies for the same key (numeric in some rows, string in others)?",
            fn=checks.check_key_type_inconsistency,
        ),
        Check(
            slug="missing-validation-layer",
            rubric_bullet=4,
            description="Is there a validation layer preventing malformed JSONB from being written?",
            fn=checks.check_missing_validation_layer,
        ),
        Check(
            slug="orphaned-legacy-keys",
            rubric_bullet=6,
            description="Are there orphaned or legacy keys accumulating from deprecated features?",
            fn=checks.check_orphaned_legacy_keys,
        ),
    ],
    out_of_scope=[
        "JSONB Structure & Governance, bullet 5 (how deeply nested is JSONB in practice, and does query "
        "code rely on brittle nested paths that break silently on structural change?) — the "
        "brittleness lives in application query code, not in the database; a read-only "
        "connection has no visibility into how the application constructs its queries.",
    ],
)
