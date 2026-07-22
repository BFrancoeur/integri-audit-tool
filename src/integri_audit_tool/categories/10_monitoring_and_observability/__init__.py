"""Rubric category 10: Monitoring & Observability.

3 of the rubric's 4 checklist bullets are implemented:
- 10.01 pg_stat_statements installed (can't confirm it's "actually reviewed"
  — that's process — but it can't be reviewed at all if absent)
- 10.02 two current-state proxies for "alerts on saturation/long-running
  queries": connection count near max_connections, and currently-active
  queries running longer than a threshold. Narrowed scope: replication lag
  and disk usage (also named in this bullet) aren't checked — disk usage
  isn't visible to Postgres at all (OS-level), and replication lag only
  applies if replicas are connected, which category 9's 09.04 already
  reports on separately.
- 10.03 tables with meaningful bloat and no vacuum recorded recently —
  distinct from category 7's 07.04, which flags bloat + no per-table
  autovacuum *configuration*; this flags bloat + no vacuum *activity*,
  which can happen even on a well-configured table if autovacuum itself
  is failing or starved.

10.04 (visibility into query performance trends over time, vs. only
point-in-time snapshots) is declared via `out_of_scope`: every pg_stat_*
view this tool reads is a cumulative snapshot since last reset, not a time
series. Whether an external system (Prometheus, Datadog, CloudWatch, etc.)
polls and retains these as trends is entirely outside Postgres — this tool
itself only ever takes point-in-time snapshots too, so it can't observe
whether anything better exists.

No `applicability` — every database has connections and tables, so this
category is never N/A.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    number=10,
    name="Monitoring & Observability",
    checks=[
        Check(
            id="10.01",
            description="Is pg_stat_statements (or equivalent) enabled and actually reviewed?",
            fn=checks.check_pg_stat_statements_installed,
        ),
        Check(
            id="10.02",
            description="Are there alerts on connection saturation, replication lag, disk usage, and long-running queries?",
            fn=checks.check_connection_saturation,
        ),
        Check(
            id="10.03",
            description="Is index/table bloat monitored, with a maintenance plan?",
            fn=checks.check_bloated_tables_without_recent_vacuum,
        ),
    ],
    out_of_scope=[
        "Category 10, bullet 10.04 (is there visibility into query performance trends over time, or only "
        "point-in-time snapshots when something breaks?) — every pg_stat_* view is a cumulative snapshot "
        "since last reset, not a time series; whether an external system polls and retains these metrics "
        "as trends is entirely outside Postgres, unobservable from a read-only connection.",
    ],
)
