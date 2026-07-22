"""Rubric category 2: JSONB Structure & Governance.

3 of the rubric's 6 checklist bullets are implemented (02.02, 02.03, 02.04).
02.01 (governing schema/registry) and 02.06 (orphaned/legacy keys) need
knowledge of intent that isn't recoverable from the database alone; 02.05
(nesting depth / brittle query paths) needs application code, not just the
data. All three are follow-up work at best, added the same way: a query in
queries.py, an interpreting function in checks.py, a Check entry below.

This is the first category to use `applicability` — per the rubric's own
guidance ("skip full-text search section entirely if none exists"), a
database with no JSONB columns at all makes this whole category N/A rather
than a clean pass.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    number=2,
    name="JSONB Structure & Governance",
    applicability=checks.is_applicable,
    checks=[
        Check(
            id="02.02",
            description="Are there inconsistent key names for the same concept (diameter vs dia vs diameter_in)?",
            fn=checks.check_key_naming_drift,
        ),
        Check(
            id="02.03",
            description="Are there type inconsistencies for the same key (numeric in some rows, string in others)?",
            fn=checks.check_key_type_inconsistency,
        ),
        Check(
            id="02.04",
            description="Is there a validation layer preventing malformed JSONB from being written?",
            fn=checks.check_missing_validation_layer,
        ),
    ],
)
