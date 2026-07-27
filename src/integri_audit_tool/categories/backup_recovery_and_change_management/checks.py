"""Interprets category-9 catalog queries into Finding objects.

One function per rubric checklist bullet (see postgres-database-audit-rubric.md,
"9. Backup, Recovery & Change Management"). Most of this category's bullets
ask about external process/tooling this tool can't see directly, so most
checks here surface partial, honest evidence (WAL archiving health, migration
tooling heuristics, replication topology) rather than a hard pass/fail
verdict — see queries.py for why. Each function takes a live connection +
config and returns zero or more Findings. Kept separate from queries.py so
this interpretation logic is unit-testable against canned row data without a
live database.
"""

from __future__ import annotations

import psycopg

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import Finding, Severity

from . import queries


def check_wal_archiving_failures(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 09.01 — are backups automated and tested, not just assumed to exist?"""
    status = queries.fetch_wal_archiver_status(conn)
    if status["failed_count"] == 0:
        return []

    last_archived = status["last_archived_time"]
    last_failed = status["last_failed_time"]
    actively_failing = last_failed is not None and (last_archived is None or last_failed > last_archived)
    severity = Severity.HIGH if actively_failing else Severity.MEDIUM

    return [
        Finding(
            check_slug="wal-archiving-failures",
            title=(
                f"WAL archiving has {'active' if actively_failing else 'historical'} failures "
                f"({status['failed_count']} total)"
            ),
            severity=severity,
            observation=(
                f"pg_stat_archiver shows {status['failed_count']} failed archive attempt(s), most "
                f"recently at {last_failed}. Last successful archive: {last_archived}."
            ),
            evidence=(
                "This only covers continuous WAL archiving (PITR), one possible backup mechanism — it "
                "says nothing about periodic pg_dump/snapshot-based backups running outside Postgres, "
                "whether any backup has ever been restore-tested, or what retention policy is in place."
            ),
            business_impact=(
                "If WAL archiving is the (or a) backup mechanism and it's actively failing, point-in-time "
                "recovery is silently degrading right now — the gap only becomes visible during an actual "
                "restore, which is the worst time to discover it."
            ),
            recommended_direction="Investigate the archive_command failures (permissions, destination availability, disk space) and confirm archiving has resumed.",
        )
    ]


def check_wal_archiving_status_summary(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 09.02 — is there a documented RTO/RPO, and does backup cadence meet it?"""
    status = queries.fetch_wal_archiver_status(conn)

    if status["archived_count"] == 0 and status["failed_count"] == 0:
        observation = (
            "No WAL archiving activity has ever been recorded on this instance — either archive_mode is "
            "off, or this is a fresh instance with nothing archived yet."
        )
    else:
        observation = (
            f"Last successful WAL archive: {status['last_archived_time']}. Lifetime totals: "
            f"{status['archived_count']} archived, {status['failed_count']} failed."
        )

    return [
        Finding(
            check_slug="wal-archiving-status-summary",
            title="WAL archiving status (for RPO comparison)",
            severity=Severity.INFORMATIONAL,
            observation=observation,
            evidence="From pg_stat_archiver — reflects continuous archiving only, not other backup mechanisms this tool can't see.",
            business_impact=(
                "This tool can't confirm whether an RTO/RPO is documented anywhere, only supply a "
                "concrete 'last successful archive' timestamp the auditor can compare against one once "
                "it exists."
            ),
            recommended_direction=(
                "If no RTO/RPO is documented, use this and the organization's actual recovery "
                "requirements to define one; then confirm backup cadence (this or otherwise) meets it."
            ),
        )
    ]


def check_migration_tracking_table_absent(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 09.03 — are schema changes version-controlled and applied through a repeatable process?"""
    if queries.fetch_migration_tracking_tables(conn):
        return []

    return [
        Finding(
            check_slug="migration-tracking-table-absent",
            title="No recognized migration-tracking table found",
            severity=Severity.LOW,
            observation=(
                "None of the common migration-tool tracking tables (Flyway, Django, Alembic, Rails, "
                "Knex, Prisma, EF Core, Goose, Sequelize, or a generic 'migrations' table) were found."
            ),
            evidence=(
                "Heuristic name match on pg_class — a team using a homegrown or differently-named "
                "migration process would also produce this result, so absence here isn't proof migrations "
                "are run manually, just an absence of the most common signal that they aren't."
            ),
            business_impact=(
                "Without a migration-tracking table, there's no way for this tool (or a new engineer) to "
                "tell from the database alone whether schema changes go through a repeatable, "
                "version-controlled process or are applied ad hoc."
            ),
            recommended_direction="Confirm how schema changes are actually applied; if it's manual/ad hoc, adopt a migration tool so changes are tracked, reviewable, and repeatable across environments.",
        )
    ]


def check_replica_topology_absent(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 09.04 — is there a staging/replica environment for meaningful migration testing?"""
    if queries.fetch_replica_count(conn) > 0:
        return []

    return [
        Finding(
            check_slug="replica-topology-absent",
            title="No streaming replicas currently connected",
            severity=Severity.LOW,
            observation="pg_stat_replication shows no replicas currently streaming from this instance.",
            evidence=(
                "A point-in-time snapshot, and a weak signal either way: many valid staging setups use "
                "periodic restores rather than streaming replication, and a connected replica doesn't by "
                "itself confirm it's used for migration testing rather than just HA/read scaling."
            ),
            business_impact=(
                "Without a replica or equivalent, schema migrations are most likely first exercised "
                "against production (or not exercised against production-like data volume/shape at all) "
                "rather than validated somewhere lower-stakes first."
            ),
            recommended_direction="Confirm whether a staging environment exists outside streaming replication (e.g. periodic restore-from-backup); if not, consider standing one up for migration testing.",
        )
    ]
