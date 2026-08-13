"""Rubric category 1: Schema Design & Normalization Boundaries.

5 of the rubric's 7 checklist bullets are implemented (01.02, 01.04, 01.05,
01.06, 01.07).

01.01 and 01.03 are declared via `out_of_scope`, not deferred: both ask
whether a schema *decision* was the right one (is this JSONB column
genuinely variable data, or an appropriate relational/JSONB split?) — that's
a judgment about intent, not something recoverable from the schema or data
alone.

**Extended (SOP merge, 2026-08-03):**
- 01.02 (structured data stored as text) is now built: numeric/date-shaped
  text columns (this category's first row-sampling check, reusing
  jsonb_structure_and_governance's psycopg.sql.Identifier pattern),
  varchar with no declared length, and `money`-type usage. The SOP's fourth
  sub-signal for this bullet ("inconsistent timestamp types across related
  tables") isn't built separately — 01.05's schema-drift check already
  catches it, since two tables' same-named column with different types is
  exactly what that check already flags.
- 01.04's `missing-foreign-keys` severity is bumped to HIGH (was MEDIUM) —
  the SOP calls this "one of the highest-severity findings in any audit."
  It also now covers ON DELETE CASCADE constraints whose child table
  doesn't look like an owned/dependent relationship by name, under the
  same slug (a DDL-shape finding about FK constraints, same as the rest of
  this check).
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    slug="schema-design-and-normalization-boundaries",
    name="Schema Design & Normalization Boundaries",
    checks=[
        Check(
            slug="structured-data-stored-as-text",
            rubric_bullet=2,
            description=(
                "Are there columns storing structured data as text that should be typed (dates as "
                "strings, numbers as text, comma-separated lists), oversized/unbounded varchar, or "
                "money-typed columns?"
            ),
            fn=checks.check_structured_data_stored_as_text,
        ),
        Check(
            slug="missing-foreign-keys",
            rubric_bullet=4,
            description="Are foreign key constraints present where relationships exist?",
            fn=checks.check_missing_foreign_keys,
        ),
        Check(
            slug="schema-drift",
            rubric_bullet=5,
            description="Is there evidence of schema drift — same concept represented differently across tables?",
            fn=checks.check_schema_drift,
        ),
        Check(
            slug="primary-key-consistency",
            rubric_bullet=6,
            description="Are primary keys and identity columns used consistently?",
            fn=checks.check_primary_key_consistency,
        ),
        Check(
            slug="repeating-column-groups",
            rubric_bullet=7,
            description=(
                "Is a repeating value (period, location, category) spread across similarly-named "
                "columns instead of normalized into rows?"
            ),
            fn=checks.check_repeating_column_groups,
        ),
    ],
    out_of_scope=[
        "Schema Design & Normalization Boundaries, bullet 1 (are JSONB columns used for genuinely variable/sparse "
        "attributes, or as a substitute for proper normalization?) — this requires knowing "
        "the business intent behind a schema decision, which isn't recoverable from the "
        "schema or data alone; a read-only connection can describe what exists, not why it "
        "was chosen.",
        "Schema Design & Normalization Boundaries, bullet 3 (is there an appropriate split between core relational "
        "columns and flexible JSONB attributes?) — \"appropriate\" is a judgment call about "
        "intended design, not something a database connection can verify independently of "
        "that intent.",
    ],
)
