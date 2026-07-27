"""Rubric category 3: Indexing Strategy.

Fully worked example category — proves the queries.py/checks.py split, the
CategoryModule registry contract, and end-to-end report rendering. Only 3 of
the rubric's 7 checklist bullets are implemented so far (03.01, 03.02, 03.04);
the remainder are deferred, not out of scope — each is mechanically buildable
from catalog/statistics access already in use elsewhere in this tool, just not
built yet: 03.03 (B-tree indexes on high-selectivity filter/join/sort columns)
from `pg_stats.n_distinct` plus a check for a matching index, the same
statistics category 6 already reads; 03.05 (range queries against JSONB with
no promoted column) from `pg_stat_statements` query-text pattern matching;
03.06 (write amplification from excessive indexing on high-churn tables) from
`pg_stat_user_tables` write counts plus index count; 03.07 (underused partial/
expression indexes) from a `pg_indexes` text heuristic. Added the same way as
any other bullet: a query in queries.py, an interpreting function in
checks.py, a Check entry below.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    slug="indexing-strategy",
    name="Indexing Strategy",
    checks=[
        Check(
            slug="unused-indexes",
            rubric_bullet=1,
            description="Do query patterns match the indexes that exist? Look for indexes that are never used.",
            fn=checks.check_unused_indexes,
        ),
        Check(
            slug="gin-usage",
            rubric_bullet=2,
            description="Is GIN used appropriately for JSONB containment (@>) and full-text search?",
            fn=checks.check_gin_usage,
        ),
        Check(
            slug="redundant-indexes",
            rubric_bullet=4,
            description="Are there redundant or overlapping indexes on the same table?",
            fn=checks.check_redundant_indexes,
        ),
    ],
)
