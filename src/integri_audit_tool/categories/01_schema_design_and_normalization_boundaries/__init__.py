"""Rubric category 1: Schema Design & Normalization Boundaries.

3 of the rubric's 6 checklist bullets are implemented (01.04, 01.05, 01.06).
01.01, 01.02, 01.03 require semantic judgment (e.g. "is this JSONB usage
genuinely variable data") or row-sampling that isn't implemented yet — they're
follow-up work, added the same way: a query in queries.py, an interpreting
function in checks.py, a Check entry below.
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
)
