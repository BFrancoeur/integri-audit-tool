"""Storage Health & Maintenance — new category from the SOP merge (2026-08-03).

Consolidates table/index bloat, TOAST storage, and vacuum/replication-slot
root-cause diagnostics that don't fit cleanly under any pre-existing
category. Two checks (table-bloat, large-toast-on-hot-tables) are moved from
Scale & Growth Readiness's former 07.04/07.05 — see that category's
__init__.py docstring — widened and rejoined here with the new content the
SOP called for: index bloat, an index-to-table size-ratio outlier check,
TOAST storage-strategy (EXTENDED vs. EXTERNAL), autovacuum explicitly
disabled at the table level, and the xmin-horizon root-cause check
(long-running transactions / abandoned replication slots), all of which
belong with bloat conceptually but had no home before this category existed.

Not in the original rubric document, same precedent as
lot-and-certification-traceability: bullet numbers are authored fresh here,
not derived from any pre-existing numbering.

No `applicability` — every database has tables, so this category is never N/A.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    slug="storage-health-and-maintenance",
    name="Storage Health & Maintenance",
    checks=[
        Check(
            slug="table-bloat",
            rubric_bullet=1,
            description="Is table bloat within a healthy range, measured directly where possible?",
            fn=checks.check_table_bloat,
        ),
        Check(
            slug="index-bloat",
            rubric_bullet=2,
            description="Is B-tree index bloat within a healthy range?",
            fn=checks.check_index_bloat,
        ),
        Check(
            slug="index-to-table-size-ratio",
            rubric_bullet=3,
            description="Is any index larger than the table it indexes?",
            fn=checks.check_index_to_table_size_ratio,
        ),
        Check(
            slug="large-toast-on-hot-tables",
            rubric_bullet=4,
            description="Are large values causing TOAST-related overhead on frequently-accessed rows?",
            fn=checks.check_large_toast_on_hot_tables,
        ),
        Check(
            slug="toast-storage-strategy",
            rubric_bullet=5,
            description="Is TOAST storage strategy (EXTENDED vs. EXTERNAL) appropriate for the access pattern?",
            fn=checks.check_toast_storage_strategy,
        ),
        Check(
            slug="autovacuum-explicitly-disabled",
            rubric_bullet=6,
            description="Is autovacuum explicitly disabled on any table?",
            fn=checks.check_autovacuum_explicitly_disabled,
        ),
        Check(
            slug="xmin-horizon-risk",
            rubric_bullet=7,
            description="Is a long-running transaction or abandoned replication slot holding back the xmin horizon?",
            fn=checks.check_xmin_horizon_risk,
        ),
    ],
)
