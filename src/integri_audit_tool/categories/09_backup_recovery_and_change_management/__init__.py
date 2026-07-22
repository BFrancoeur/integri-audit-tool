"""Rubric category 9: Backup, Recovery & Change Management.

All 4 of the rubric's checklist bullets are implemented, but honestly: most
of what this category asks about (tested restores, documented RTO/RPO,
retention policy, whether a staging environment mirrors production closely
enough to be meaningful) is external process and tooling, invisible to a
read-only DB connection. What Postgres does expose are partial, genuinely
useful signals — WAL archiving health (pg_stat_archiver), migration-tool
tracking-table heuristics, and current replication topology
(pg_stat_replication) — so most checks here surface evidence for a human
auditor rather than a pass/fail verdict:
- 09.01 WAL archiving failures (the one check with real teeth — an actively
  failing archive_command is a concrete, current problem, not a documentation
  gap)
- 09.02 WAL archiving recency, always reported as Informational context for
  comparing against a documented RPO once one exists
- 09.03 no recognized migration-tool tracking table found
- 09.04 no streaming replicas currently connected

No `applicability` — pg_stat_archiver and pg_stat_replication always exist
(reporting empty/zero when unconfigured), so this category is never N/A.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    number=9,
    name="Backup, Recovery & Change Management",
    checks=[
        Check(
            id="09.01",
            description="Are backups automated and tested (restore drills), not just assumed to exist?",
            fn=checks.check_wal_archiving_failures,
        ),
        Check(
            id="09.02",
            description="Is there a documented RTO/RPO, and does current backup cadence meet it?",
            fn=checks.check_wal_archiving_status_summary,
        ),
        Check(
            id="09.03",
            description="Are schema changes version-controlled and applied through a repeatable process?",
            fn=checks.check_migration_tracking_table_absent,
        ),
        Check(
            id="09.04",
            description="Is there a staging/replica environment for meaningful migration testing?",
            fn=checks.check_replica_topology_absent,
        ),
    ],
)
