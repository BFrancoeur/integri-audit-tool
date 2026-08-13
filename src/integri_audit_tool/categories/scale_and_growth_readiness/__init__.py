"""Rubric category 7: Scale & Growth Readiness.

3 of the rubric's 5 original checklist bullets remain here:
- 07.01 measured slow queries (pg_stat_statements — degrades to
  Informational if not installed)
- 07.02 current table/index footprint (pg_total_relation_size —
  Informational: this tool can measure current size, not whether growth is
  *tracked over time* or whether a threshold is *documented*, so it only
  supplies the numbers, not a verdict)
- 07.03 tenant-shaped columns without row-level security enabled
  (pg_class.relrowsecurity — heuristic name match, doesn't prove isolation
  is actually broken, only that the DB-level backstop isn't engaged)

**Moved (SOP merge, 2026-08-03):** 07.04 (autovacuum tuning vs. bloat) and
07.05 (TOAST overhead from large values, widened beyond JSONB-only) moved to
the new `storage-health-and-maintenance` category, alongside new index-bloat,
TOAST-storage-strategy, autovacuum-disabled, and xmin-horizon checks that
belong with them conceptually. This category now focuses purely on capacity/
growth-trajectory questions (is anything measurably slow now, how big is the
footprint, is tenant isolation engaged) rather than storage/vacuum health.

No `applicability` — every database has tables, so this category is never N/A.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    slug="scale-and-growth-readiness",
    name="Scale & Growth Readiness",
    checks=[
        Check(
            slug="slow-queries",
            rubric_bullet=1,
            description="At current row counts, are there any operations already showing measured degraded performance?",
            fn=checks.check_slow_queries,
        ),
        Check(
            slug="largest-tables",
            rubric_bullet=2,
            description="Is table/index size growth tracked, with a stated volume threshold for architecture change?",
            fn=checks.check_largest_tables,
        ),
        Check(
            slug="tenant-columns-without-rls",
            rubric_bullet=3,
            description="Does the architecture isolate tenant/category data access patterns?",
            fn=checks.check_tenant_columns_without_rls,
        ),
    ],
)
