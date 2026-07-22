"""Rubric category 4: Full-Text & Structured Search Behavior.

2 of the rubric's 6 checklist bullets are implemented (04.01, 04.02). The
other four (04.03 combining structured+free-text filters efficiently, 04.04
relevance ranking, 04.05 safe query parsing via websearch_to_tsquery, 04.06
facets matching governed attributes) live in application/query code, not the
database — a read-only DB connection can't see how search queries are built
or how UI facets are populated, so they aren't automatable here.

Uses `applicability`: a database with no tsvector columns at all makes this
whole category N/A, per the rubric's own guidance to skip full-text search
sections that don't apply.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    number=4,
    name="Full-Text & Structured Search Behavior",
    applicability=checks.is_applicable,
    checks=[
        Check(
            id="04.01",
            description="Is full-text search using tsvector/tsquery with GIN indexing, or falling back to unindexable ILIKE?",
            fn=checks.check_missing_fulltext_index,
        ),
        Check(
            id="04.02",
            description="Is the tsvector kept in sync via a generated column or trigger, not manually maintained?",
            fn=checks.check_tsvector_sync_mechanism,
        ),
    ],
)
