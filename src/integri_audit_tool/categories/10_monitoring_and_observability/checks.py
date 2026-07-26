"""Interprets category-10 catalog/statistics queries into Finding objects.

One function per rubric checklist bullet (see postgres-database-audit-rubric.md,
"10. Monitoring & Observability") that's assessable from read-only access.
10.04 (visibility into query performance trends over time) is declared in
`out_of_scope` in __init__.py — every pg_stat_* view is a cumulative snapshot
since last reset, not a time series; whether an external system polls and
retains these as trends is outside Postgres entirely. Each function here
takes a live connection + config and returns zero or more Findings. Kept
separate from queries.py so this interpretation logic is unit-testable
against canned row data without a live database.
"""

from __future__ import annotations

import psycopg

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import Finding, Severity

from . import queries

_HIGH_CONNECTION_SATURATION_RATIO = 0.8
_HIGH_QUERY_DURATION_MULTIPLE = 3
"""A running query at >= this multiple of LONG_RUNNING_QUERY_THRESHOLD escalates to High."""


def check_pg_stat_statements_installed(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 10.01 — is pg_stat_statements (or equivalent) enabled and actually reviewed?"""
    if queries.is_pg_stat_statements_available(conn):
        return []

    return [
        Finding(
            check_slug="pg-stat-statements-installed",
            title="pg_stat_statements is not installed",
            severity=Severity.MEDIUM,
            observation="The pg_stat_statements extension is not installed on this database.",
            evidence=(
                "Checked via pg_extension. Whether an installed pg_stat_statements is actually reviewed "
                "by anyone is a process question this tool can't assess either way — but it can't be "
                "reviewed at all if it isn't installed."
            ),
            business_impact=(
                "Without it, there's no aggregate view of which queries run most often or cost the most "
                "— performance problems are only noticed anecdotally rather than measured."
            ),
            recommended_direction="Enable pg_stat_statements (shared_preload_libraries + CREATE EXTENSION) as a baseline for query-level observability.",
        )
    ]


def check_connection_saturation(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 10.02 — are there alerts on connection saturation and long-running queries?

    Narrowed scope: this checks current-state proxies for two of the bullet's
    four alert targets (connection saturation, long-running queries); replication
    lag and disk usage aren't checked here (see class/module docs for why).
    """
    findings = []

    saturation = queries.fetch_connection_saturation(conn)
    if saturation["max_connections"]:
        ratio = saturation["current_connections"] / saturation["max_connections"]
        if ratio >= _HIGH_CONNECTION_SATURATION_RATIO:
            findings.append(
                Finding(
                    check_slug="connection-saturation",
                    title=f"Connection usage near saturation ({ratio:.0%} of max_connections)",
                    severity=Severity.HIGH,
                    observation=(
                        f"{saturation['current_connections']} of {saturation['max_connections']} "
                        f"max_connections in use ({ratio:.0%}) at audit time."
                    ),
                    evidence="Point-in-time snapshot from pg_stat_activity + pg_settings, not a trend — doesn't confirm an alert exists at this or any threshold.",
                    business_impact=(
                        "Once connections are exhausted, every new connection attempt (app requests, "
                        "admin access) fails outright — this is a hard ceiling, not a gradual slowdown."
                    ),
                    recommended_direction="Add an alert on connection count approaching max_connections, and investigate whether a connection pooler would reduce steady-state usage.",
                )
            )

    for row in queries.fetch_long_running_active_queries(conn):
        duration = row["query_duration"]
        severity = (
            Severity.HIGH
            if duration >= queries.LONG_RUNNING_QUERY_THRESHOLD * _HIGH_QUERY_DURATION_MULTIPLE
            else Severity.MEDIUM
        )
        findings.append(
            Finding(
                check_slug="connection-saturation",
                title=f"Long-running active query (pid {row['pid']}, running {duration})",
                severity=severity,
                observation=(
                    f"Session pid={row['pid']} (user '{row['usename']}', app '{row['application_name']}') "
                    f"has been actively executing for {duration}. Query: "
                    f"{row['query'] or '(not visible to this role)'}"
                ),
                evidence="Point-in-time snapshot from pg_stat_activity, not a trend — doesn't confirm an alert exists for this.",
                business_impact="A long-running query holds locks and consumes resources for its entire duration, and can block other queries or DDL waiting behind it.",
                recommended_direction="Confirm whether this duration is expected (a batch job) or a runaway query; consider statement_timeout as a backstop.",
            )
        )

    return findings


def check_bloated_tables_without_recent_vacuum(
    conn: psycopg.Connection, config: AuditConfig
) -> list[Finding]:
    """Rubric 10.03 — is index/table bloat monitored, with a maintenance plan?"""
    findings = []
    for row in queries.fetch_bloated_tables_without_recent_vacuum(conn):
        ratio = row["dead_tuple_ratio"]
        findings.append(
            Finding(
                check_slug="bloated-tables-without-recent-vacuum",
                title=f"Bloat present with no recent vacuum: {row['table_name']} ({ratio:.0%})",
                severity=Severity.MEDIUM,
                observation=(
                    f"{row['schema_name']}.{row['table_name']} has {ratio:.0%} dead tuples "
                    f"(~{row['n_dead_tup']} of ~{row['n_live_tup']} live) and no vacuum recorded within "
                    f"the last {queries.VACUUM_STALENESS_THRESHOLD}. Last manual vacuum: "
                    f"{row['last_vacuum']}; last autovacuum: {row['last_autovacuum']}."
                ),
                evidence=(
                    "From pg_stat_user_tables. Distinct from a per-table autovacuum *configuration* gap — "
                    "this table could be tuned perfectly and still show this if autovacuum is failing, "
                    "disabled, or starved cluster-wide; either way, maintenance isn't actually happening."
                ),
                business_impact=(
                    "Bloat that isn't being reclaimed degrades index efficiency and query performance over "
                    "time, and can eventually force an emergency VACUUM FULL (which locks the table) or a "
                    "wraparound-prevention autovacuum at the worst possible time."
                ),
                recommended_direction="Investigate why vacuum isn't running on this table (autovacuum disabled? erroring? starved by other work?) and consider pg_repack for an online fix if bloat is already severe.",
            )
        )
    return findings
