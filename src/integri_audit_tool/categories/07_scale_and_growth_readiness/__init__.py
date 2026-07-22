"""Rubric category 7: Scale & Growth Readiness.

All 5 of the rubric's checklist bullets are implemented — the first category
where every bullet turned out to be assessable from read-only catalog/
statistics access:
- 07.01 measured slow queries (pg_stat_statements — degrades to
  Informational if not installed)
- 07.02 current table/index footprint (pg_total_relation_size —
  Informational: this tool can measure current size, not whether growth is
  *tracked over time* or whether a threshold is *documented*, so it only
  supplies the numbers, not a verdict)
- 07.03 tenant-shaped columns without row-level security enabled
  (pg_class.relrowsecurity — heuristic name match, doesn't prove isolation
  is actually broken, only that the DB-level backstop isn't engaged)
- 07.04 high dead-tuple bloat with no per-table autovacuum tuning
  (pg_stat_user_tables + pg_class.reloptions)
- 07.05 large JSONB values likely causing TOAST overhead on a
  frequently-accessed table (pg_stats.avg_width + scan counts)

No `applicability` — every database has tables, so this category is never N/A.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    number=7,
    name="Scale & Growth Readiness",
    checks=[
        Check(
            id="07.01",
            description="At current row counts, are there any operations already showing measured degraded performance?",
            fn=checks.check_slow_queries,
        ),
        Check(
            id="07.02",
            description="Is table/index size growth tracked, with a stated volume threshold for architecture change?",
            fn=checks.check_largest_tables,
        ),
        Check(
            id="07.03",
            description="Does the architecture isolate tenant/category data access patterns?",
            fn=checks.check_tenant_columns_without_rls,
        ),
        Check(
            id="07.04",
            description="Is autovacuum tuned for the table's write/update pattern, or left at defaults on a high-churn table?",
            fn=checks.check_high_bloat_tables_without_tuning,
        ),
        Check(
            id="07.05",
            description="Are large JSONB documents causing TOAST-related overhead on frequently-accessed rows?",
            fn=checks.check_large_jsonb_on_hot_tables,
        ),
    ],
)
