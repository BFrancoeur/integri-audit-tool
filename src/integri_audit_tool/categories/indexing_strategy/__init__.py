"""Rubric category 3: Indexing Strategy.

Fully worked example category — proves the queries.py/checks.py split, the
CategoryModule registry contract, and end-to-end report rendering. All 7 of
the rubric's checklist bullets are now implemented.

**Extended (SOP merge, 2026-08-03):** 03.01's `unused-indexes` check now also
covers unindexed foreign keys, sequential-scan-heavy tables, and composite
index column-order mismatches — three more angles on the same underlying
question ("do the indexes that exist match how the table is actually
queried"), bundled under the same slug rather than given new bullet numbers,
the same way 08.04 already bundles three findings under one slug.

**Added (2026-08-08):** the four previously-deferred bullets, each
mechanically buildable from catalog/statistics access already in use
elsewhere in this tool:
- 03.03 (`high-selectivity-columns-without-index`) — `pg_stats.n_distinct`
  plus a check for a matching index, the same statistics category 6 already
  reads. Doesn't confirm the column is actually filtered/joined/sorted on
  (that needs query-log access this check doesn't have), so it's capped at
  LOW severity and framed as a candidate, not a proven finding.
- 03.05 (`unpromoted-jsonb-range-queries`) — `pg_stat_statements` query-text
  pattern matching for a JSONB column name near a `->>`/`#>>` extraction
  operator combined with a comparison operator or BETWEEN, same heuristic
  shape (and same LOW-severity caveat) as 03.01's composite-index-mismatch
  check.
- 03.06 (`excessive-indexing-write-amplification`) — `pg_stat_user_tables`
  write counts plus an index count per table, pure catalog/stats, no
  `pg_stat_statements` dependency.
- 03.07 (`underused-partial-indexes`) — a `pg_indexes`/`pg_attribute` text
  heuristic: a non-partial index leading with a boolean or status/flag-named
  column is a plausible partial-index candidate. Doesn't confirm the actual
  value distribution is skewed, so it's a candidate list, not a proven
  finding.
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
            slug="high-selectivity-columns-without-index",
            rubric_bullet=3,
            description=(
                "Are B-tree indexes present on high-selectivity columns used in equality/range filters, "
                "joins, and sort/order-by clauses?"
            ),
            fn=checks.check_high_selectivity_columns_without_index,
        ),
        Check(
            slug="redundant-indexes",
            rubric_bullet=4,
            description="Are there redundant or overlapping indexes on the same table?",
            fn=checks.check_redundant_indexes,
        ),
        Check(
            slug="unpromoted-jsonb-range-queries",
            rubric_bullet=5,
            description=(
                "Are range queries (numeric or date) being run against JSONB fields with no promoted column?"
            ),
            fn=checks.check_unpromoted_jsonb_range_queries,
        ),
        Check(
            slug="excessive-indexing-write-amplification",
            rubric_bullet=6,
            description=(
                "Is there an index maintenance concern — high write volume tables with excessive "
                "indexing, causing write amplification?"
            ),
            fn=checks.check_excessive_indexing_write_amplification,
        ),
        Check(
            slug="underused-partial-indexes",
            rubric_bullet=7,
            description=(
                "Are partial indexes or expression indexes used where they'd meaningfully narrow index "
                "size (e.g., indexing only WHERE active = true)?"
            ),
            fn=checks.check_underused_partial_indexes,
        ),
    ],
)
