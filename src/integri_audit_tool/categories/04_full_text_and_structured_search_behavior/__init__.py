"""Rubric category 4: Full-Text & Structured Search Behavior.

5 of the rubric's 6 checklist bullets are implemented. 04.01/04.02 come from
catalog metadata; 04.03/04.04/04.05 come from pg_stat_statements (the actual
SQL text the application has run), since those bullets describe query-code
behavior invisible to schema introspection alone — each degrades gracefully
to an Informational finding if the extension isn't installed.

04.06 (facets generated dynamically from governed attributes vs hardcoded) is
declared via `out_of_scope`, not just omitted: it's UI/frontend logic, which
no read-only Postgres connection can ever see, regardless of how much SQL
introspection this tool grows — a permanent limit, not a "not yet
implemented." It shows up in the report's Out of Scope section by name.

Uses `applicability`: a database with no tsvector columns at all makes this
whole category N/A, per the rubric's own guidance to skip full-text search
sections that don't apply.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    slug="full-text-and-structured-search-behavior",
    name="Full-Text & Structured Search Behavior",
    applicability=checks.is_applicable,
    checks=[
        Check(
            slug="missing-fulltext-index",
            rubric_bullet=1,
            description="Is full-text search using tsvector/tsquery with GIN indexing, or falling back to unindexable ILIKE?",
            fn=checks.check_missing_fulltext_index,
        ),
        Check(
            slug="tsvector-sync-mechanism",
            rubric_bullet=2,
            description="Is the tsvector kept in sync via a generated column or trigger, not manually maintained?",
            fn=checks.check_tsvector_sync_mechanism,
        ),
        Check(
            slug="combined-structured-and-freetext-queries",
            rubric_bullet=3,
            description="Are structured filters (JSONB containment) and free-text search combined efficiently in the same query?",
            fn=checks.check_combined_structured_and_freetext_queries,
        ),
        Check(
            slug="relevance-ranking",
            rubric_bullet=4,
            description="Does search relevance ranking (ts_rank or equivalent) exist?",
            fn=checks.check_relevance_ranking,
        ),
        Check(
            slug="safe-tsquery-parsing",
            rubric_bullet=5,
            description="Is query input handled through websearch_to_tsquery rather than raw string concatenation into tsquery?",
            fn=checks.check_safe_tsquery_parsing,
        ),
    ],
    out_of_scope=[
        "Category 4, bullet 04.06 (are facet/filter UI options generated dynamically from governed "
        "attributes, or hardcoded/inconsistent with the data?) — this is frontend/UI logic, not visible "
        "to a read-only Postgres connection, and can never be assessed by this tool."
    ],
)
