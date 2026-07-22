"""Rubric category 6: Data Quality & Integrity.

5 of the rubric's 6 checklist bullets are implemented. Unlike category 2
(which had to sample actual JSONB row data), most of the signal here is
already collected by Postgres's own ANALYZE process and exposed via
pg_stats/pg_stat_user_tables — cheap, catalog-only, no row scanning:
- 06.01 high null fraction in nullable columns (evidence-gathering,
  Informational — can't know which fields are "expected to be populated")
- 06.03 foreign keys created NOT VALID and never validated
- 06.04 near-unique columns (by n_distinct) with no unique constraint
- 06.05 nullable columns that are never actually null (schema looser than
  actual data — the flip side of 06.01, same underlying stats)
- 06.06 audit timestamp columns (created_at/updated_at/modified_at by name)
  with a nonzero null rate

06.02 (malformed JSONB entries — wrong types, unexpected nesting, empty
objects) is deferred, not out of scope: it's achievable with the same
row-sampling approach category 2 used for JSONB key/type checks, just not
built yet.

No `applicability` — every database has tables and columns, so this
category is never N/A.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    number=6,
    name="Data Quality & Integrity",
    checks=[
        Check(
            id="06.01",
            description="What percentage of rows have null values in fields expected to be populated?",
            fn=checks.check_high_null_fraction_columns,
        ),
        Check(
            id="06.03",
            description="Are there orphaned foreign key references or missing referential integrity?",
            fn=checks.check_unvalidated_foreign_keys,
        ),
        Check(
            id="06.04",
            description="Are there duplicate records that should be unique (missing unique constraints)?",
            fn=checks.check_near_unique_columns_without_constraint,
        ),
        Check(
            id="06.05",
            description="Is there a discrepancy between what the schema allows and what the data contains?",
            fn=checks.check_never_null_nullable_columns,
        ),
        Check(
            id="06.06",
            description="Are timestamp/audit columns consistently populated and reliable for change tracking?",
            fn=checks.check_audit_timestamp_columns_have_nulls,
        ),
    ],
)
