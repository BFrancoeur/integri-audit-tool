"""Rubric category 3: Indexing Strategy.

Fully worked example category — proves the queries.py/checks.py split, the
CategoryModule registry contract, and end-to-end report rendering. Only 3 of
the rubric's 7 checklist bullets are implemented so far (03.01, 03.02, 03.04);
the remainder (03.03, 03.05, 03.06, 03.07) are follow-up work, added the same
way: a query in queries.py, an interpreting function in checks.py, a Check
entry below.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    number=3,
    name="Indexing Strategy",
    checks=[
        Check(
            id="03.01",
            description="Do query patterns match the indexes that exist? Look for indexes that are never used.",
            fn=checks.check_unused_indexes,
        ),
        Check(
            id="03.02",
            description="Is GIN used appropriately for JSONB containment (@>) and full-text search?",
            fn=checks.check_gin_usage,
        ),
        Check(
            id="03.04",
            description="Are there redundant or overlapping indexes on the same table?",
            fn=checks.check_redundant_indexes,
        ),
    ],
)
