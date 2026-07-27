"""Rubric category 1: Schema Design & Normalization Boundaries.

3 of the rubric's 6 checklist bullets are implemented (01.04, 01.05, 01.06).
01.02 (structured data stored as text — dates/numbers/lists as strings) is
follow-up work, added the same way as any other bullet: a query in
queries.py, an interpreting function in checks.py, a Check entry below —
mechanically buildable via regex/pattern heuristics on text columns, same
toolkit already in use elsewhere.

01.01 and 01.03 are declared via `out_of_scope`, not deferred: both ask
whether a schema *decision* was the right one (is this JSONB column
genuinely variable data, or an appropriate relational/JSONB split?) — that's
a judgment about intent, not something recoverable from the schema or data
alone.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    slug="schema-design-and-normalization-boundaries",
    name="Schema Design & Normalization Boundaries",
    checks=[
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
