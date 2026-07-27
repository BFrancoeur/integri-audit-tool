"""Rubric category 5: Query Patterns & Application Interaction.

4 of the rubric's 6 checklist bullets are implemented:
- 05.01 N+1 candidates and 05.03 OFFSET pagination usage come from
  pg_stat_statements (degrade to Informational if it isn't installed, same
  pattern as category 4).
- 05.04 idle-in-transaction sessions and 05.06 slow-query monitoring presence
  come from pg_stat_activity/pg_settings — core Postgres, no extension needed.

05.02 and 05.05 are declared via `out_of_scope`, not attempted:
- 05.02 (parameterized queries vs string concatenation): pg_stat_statements
  normalizes literal constants into $N placeholders based on the parsed query
  tree, regardless of whether they arrived as a bind parameter or were
  concatenated directly into the SQL text before being sent — both produce
  identical normalized query text. There's no reliable way to tell these
  apart from query text alone (the same limitation we ran into with
  websearch_to_tsquery vs raw concatenation in category 4, which *is*
  checkable there only because it's about which function is called, not how
  the value reached it).
- 05.05 (connection pooling configured, e.g. PgBouncer, vs raw per-request
  connections): a point-in-time connection count from pg_stat_activity is too
  indirect a proxy — a low-traffic pooled app and a low-traffic unpooled app
  can look identical in a single snapshot. No reliable signal without
  historical connection-churn data this tool doesn't collect.

No `applicability` here — unlike JSONB or full-text search, every Postgres
database has queries, transactions, and connections, so this category is
never N/A.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    slug="query-patterns-and-application-interaction",
    name="Query Patterns & Application Interaction",
    checks=[
        Check(
            slug="n-plus-one-candidates",
            rubric_bullet=1,
            description="Evidence of N+1 query patterns (many small queries per page load instead of one joined/batched query)?",
            fn=checks.check_n_plus_one_candidates,
        ),
        Check(
            slug="offset-pagination",
            rubric_bullet=3,
            description="Is pagination implemented efficiently (keyset/cursor-based) or via OFFSET at scale?",
            fn=checks.check_offset_pagination,
        ),
        Check(
            slug="idle-in-transaction-sessions",
            rubric_bullet=4,
            description="Are transactions scoped appropriately, not held open unnecessarily?",
            fn=checks.check_idle_in_transaction_sessions,
        ),
        Check(
            slug="slow-query-monitoring",
            rubric_bullet=6,
            description="Are slow queries logged and monitored, or only noticed anecdotally?",
            fn=checks.check_slow_query_monitoring,
        ),
    ],
    out_of_scope=[
        "Query Patterns & Application Interaction, bullet 2 (are queries parameterized or built via string concatenation?) — "
        "pg_stat_statements normalizes constants into placeholders from the parsed query tree regardless "
        "of whether they arrived as a bind parameter or were concatenated into the SQL text, so the two "
        "are indistinguishable from query text alone.",
        "Query Patterns & Application Interaction, bullet 5 (is connection pooling like PgBouncer configured, or does the app open "
        "raw connections per request?) — a point-in-time connection count is too indirect a proxy to "
        "reliably tell pooled from unpooled traffic; this tool doesn't collect the connection-churn "
        "history that would actually distinguish them.",
    ],
)
