"""Rubric category 6: Data Quality & Integrity.

9 of the rubric's 6 original checklist bullets are implemented -- more
bullets than the original rubric had, since the SOP merge (2026-08-03)
added three (06.07-06.09) with no original-rubric equivalent. Unlike
category 2 (which had to sample actual JSONB row data), most of the
original signal here is collected by Postgres's own ANALYZE process and
exposed via pg_stats/pg_stat_user_tables — cheap, catalog-only, no row
scanning:
- 06.01 high null fraction in nullable columns (evidence-gathering,
  Informational — can't know which fields are "expected to be populated")
- 06.03 foreign keys created NOT VALID and never validated
- 06.04 near-unique columns (by n_distinct) with no unique constraint
- 06.05 nullable columns effectively always populated (near-zero null
  fraction, loosened from strict-zero in the SOP merge — schema looser
  than actual data, the flip side of 06.01, same underlying stats)
- 06.06 audit timestamp columns (created_at/updated_at/modified_at by name)
  with a nonzero null rate

**Added (2026-08-08):** 06.02 (`malformed-jsonb-entries`) — achieved with the
same row-sampling approach category 2 used for JSONB key/type checks, but
deliberately scoped to just one symptom: empty ('{}'/'[]') documents where
data was expected. The rubric bullet's other named symptoms (wrong types,
unexpected nesting) are already covered at finer grain by category 2's
key-type-inconsistency check, which operates per-key rather than on the
document as a whole — building a redundant document-level version of that
signal here would just double-report the same underlying finding.

**Added (SOP merge, 2026-08-03):**
- 06.07 CHECK-constraint coverage + orphaned/inconsistent enum-like
  free-text columns, merged into one check — both SOP write-ups describe
  the same signal (low-cardinality text, no CHECK, no lookup-table FK).
- 06.08 default-value audit, scoped to boolean/status-shaped NOT NULL
  columns with no database DEFAULT (a blanket sweep over every NOT NULL
  column without a default would be mostly noise).
- 06.09 orphaned-row sampling — this category's first row-sampling check.
  Scoped to NOT VALID foreign key constraints only (06.03 already finds
  these structurally; this samples the actual child rows to confirm real
  orphans exist). Deliberately does *not* attempt undeclared FK-shaped
  columns (schema_design's heuristic) — guessing which table an
  undeclared column like `customer_id` probably references has no
  reliable naming convention to lean on, and a wrong guess here means
  confidently reporting orphans against the wrong table.

**Explicitly deferred, not designed (SOP A7):** cross-table consistency
checks (e.g. a stored `total_price` that should equal `qty * unit_price`)
and "conflicting data across related tables" are genuinely open-ended and
client-specific — there's no generic way to express an arbitrary business
formula without a config format this codebase has no precedent for. Noted
here rather than built, same treatment as 06.02's deferral above.

No `applicability` — every database has tables and columns, so this
category is never N/A.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    slug="data-quality-and-integrity",
    name="Data Quality & Integrity",
    checks=[
        Check(
            slug="high-null-fraction-columns",
            rubric_bullet=1,
            description="What percentage of rows have null values in fields expected to be populated?",
            fn=checks.check_high_null_fraction_columns,
        ),
        Check(
            slug="malformed-jsonb-entries",
            rubric_bullet=2,
            description=(
                "Are there malformed JSONB entries (wrong types, unexpected nesting, empty objects "
                "where data was expected)?"
            ),
            fn=checks.check_malformed_jsonb_entries,
        ),
        Check(
            slug="unvalidated-foreign-keys",
            rubric_bullet=3,
            description="Are there orphaned foreign key references or missing referential integrity?",
            fn=checks.check_unvalidated_foreign_keys,
        ),
        Check(
            slug="near-unique-columns-without-constraint",
            rubric_bullet=4,
            description="Are there duplicate records that should be unique (missing unique constraints)?",
            fn=checks.check_near_unique_columns_without_constraint,
        ),
        Check(
            slug="never-null-nullable-columns",
            rubric_bullet=5,
            description="Is there a discrepancy between what the schema allows and what the data contains?",
            fn=checks.check_never_null_nullable_columns,
        ),
        Check(
            slug="audit-timestamp-columns-have-nulls",
            rubric_bullet=6,
            description="Are timestamp/audit columns consistently populated and reliable for change tracking?",
            fn=checks.check_audit_timestamp_columns_have_nulls,
        ),
        Check(
            slug="low-cardinality-ungoverned-columns",
            rubric_bullet=7,
            description=(
                "Is there CHECK-constraint or lookup-table coverage for low-cardinality text columns "
                "(enum-like free text)?"
            ),
            fn=checks.check_low_cardinality_ungoverned_columns,
        ),
        Check(
            slug="missing-default-on-status-like-columns",
            rubric_bullet=8,
            description="Are status/flag-shaped NOT NULL columns relying on app-layer defaults instead of a database DEFAULT?",
            fn=checks.check_missing_default_on_status_like_columns,
        ),
        Check(
            slug="orphaned-rows-on-unvalidated-foreign-keys",
            rubric_bullet=9,
            description="Sampling actual rows: do any already violate a declared but unvalidated foreign key relationship?",
            fn=checks.check_orphaned_rows_on_unvalidated_foreign_keys,
        ),
    ],
)
