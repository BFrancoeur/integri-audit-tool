"""Interprets category-5 pg_stat_statements/pg_stat_activity/pg_settings
queries into Finding objects.

One function per rubric checklist bullet (see postgres-database-audit-rubric.md,
"5. Query Patterns & Application Interaction") that's actually assessable —
05.02 (parameterization vs string concatenation) and 05.05 (connection
pooling) are declared in `out_of_scope` in __init__.py instead, since neither
has a reliable signal available from a read-only connection (see there for
why). Each function here takes a live connection + config and returns zero or
more Findings. Kept separate from queries.py so this interpretation logic is
unit-testable against canned row data without a live database.
"""

from __future__ import annotations

from datetime import timedelta

import psycopg

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import Finding, Severity

from . import queries

_LONG_IDLE_IN_TRANSACTION_THRESHOLD = timedelta(minutes=5)


def _pg_stat_statements_unavailable_finding(check_slug: str, bullet_summary: str) -> Finding:
    return Finding(
        check_slug=check_slug,
        title=f"Could not assess ({bullet_summary}): pg_stat_statements is not installed",
        severity=Severity.INFORMATIONAL,
        observation=(
            "The pg_stat_statements extension is not installed/enabled on this database, so the actual "
            "SQL text and call volume the application generates isn't available to inspect for this bullet."
        ),
        evidence="Checked via pg_extension.",
        business_impact="This aspect of query behavior can't be assessed without pg_stat_statements.",
        recommended_direction=(
            "Enable pg_stat_statements (requires adding it to shared_preload_libraries and a restart, "
            "then CREATE EXTENSION pg_stat_statements) so a future audit can assess this."
        ),
    )


def check_n_plus_one_candidates(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 05.01 — evidence of N+1 query patterns?"""
    if not queries.is_pg_stat_statements_available(conn):
        return [_pg_stat_statements_unavailable_finding("n-plus-one-candidates", "N+1 query patterns")]

    findings = []
    for row in queries.fetch_n_plus_one_candidates(conn):
        findings.append(
            Finding(
                check_slug="n-plus-one-candidates",
                title=f"Possible N+1 candidate: called {row['calls']} times, ~1 row each",
                severity=Severity.INFORMATIONAL,
                observation=(
                    f"A single-table, no-JOIN query was called {row['calls']} times, averaging "
                    f"{row['avg_rows_per_call']:.2f} rows per call: {row['query']}"
                ),
                evidence=(
                    "pg_stat_statements can't prove N+1 (no per-request grouping) — this only surfaces "
                    "high-call-count, single-row-shaped queries worth checking for a per-row loop in "
                    "application code."
                ),
                business_impact=(
                    "If this is called once per row inside a loop instead of batched into a single "
                    "joined/IN-list query, it multiplies round-trip latency and DB load with page/dataset size."
                ),
                recommended_direction=(
                    "Check the calling code path; if it's iterating and querying per item, batch it into "
                    "one query (JOIN, WHERE col = ANY($1), or a prefetch)."
                ),
            )
        )
    return findings


def check_offset_pagination(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 05.03 — is pagination keyset/cursor-based, or OFFSET at scale?"""
    if not queries.is_pg_stat_statements_available(conn):
        return [_pg_stat_statements_unavailable_finding("offset-pagination", "pagination strategy")]

    stats = queries.fetch_offset_pagination_usage(conn)
    if stats["matched_statement_count"] == 0:
        return []

    examples = "; ".join(stats["example_queries"] or [])
    return [
        Finding(
            check_slug="offset-pagination",
            title="OFFSET-based pagination in use",
            severity=Severity.LOW,
            observation=(
                f"pg_stat_statements shows {stats['matched_statement_count']} observed statement(s) using "
                "OFFSET."
            ),
            evidence=f"Example statement(s) (truncated): {examples}" if examples else "See pg_stat_statements.",
            business_impact=(
                "OFFSET pagination degrades roughly linearly with offset size — Postgres still has to "
                "scan and discard all skipped rows, so deep pages get progressively slower as the table grows."
            ),
            recommended_direction=(
                "Switch to keyset/cursor-based pagination (WHERE id > $last_seen ORDER BY id LIMIT $n) "
                "where feasible, especially for pages users are likely to page deep into."
            ),
        )
    ]


def check_idle_in_transaction_sessions(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 05.04 — are transactions scoped appropriately (not held open unnecessarily)?"""
    findings = []
    for row in queries.fetch_idle_in_transaction_sessions(conn):
        duration = row["transaction_duration"]
        severity = (
            Severity.HIGH if duration is not None and duration > _LONG_IDLE_IN_TRANSACTION_THRESHOLD else Severity.MEDIUM
        )
        findings.append(
            Finding(
                check_slug="idle-in-transaction-sessions",
                title=f"Idle-in-transaction session (pid {row['pid']}, open {duration})",
                severity=severity,
                observation=(
                    f"Session pid={row['pid']} (user '{row['usename']}', app '{row['application_name']}') "
                    f"is idle in transaction, open for {duration}. Last statement: {row['last_query'] or '(not visible to this role)'}"
                ),
                evidence=(
                    "Point-in-time snapshot from pg_stat_activity at audit time — reflects what was "
                    "happening right now, not a historical pattern. Query text for other roles' sessions "
                    "requires pg_monitor/superuser."
                ),
                business_impact=(
                    "A transaction left open holds its locks and prevents autovacuum from cleaning up "
                    "rows it could otherwise reclaim, which can cause blocking and table/index bloat "
                    "elsewhere in the database."
                ),
                recommended_direction=(
                    "Ensure application code commits/rolls back promptly after its last statement; add a "
                    "statement_timeout or idle_in_transaction_session_timeout as a backstop."
                ),
            )
        )
    return findings


def check_slow_query_monitoring(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 05.06 — are slow queries logged and monitored, or only noticed anecdotally?"""
    status = queries.fetch_slow_query_monitoring_status(conn)
    log_min_duration = status["log_min_duration_statement"]
    slow_query_logging_enabled = log_min_duration is not None and log_min_duration != "-1"

    if status["pg_stat_statements_enabled"] or status["auto_explain_loaded"] or slow_query_logging_enabled:
        return []

    return [
        Finding(
            check_slug="slow-query-monitoring",
            title="No slow-query monitoring mechanism detected",
            severity=Severity.MEDIUM,
            observation=(
                "None of the three common slow-query visibility mechanisms are active: pg_stat_statements "
                "is not installed, auto_explain is not loaded, and log_min_duration_statement is disabled "
                f"(current value: {log_min_duration!r})."
            ),
            evidence="Checked via pg_extension and pg_settings.",
            business_impact=(
                "Without any of these, slow queries are only noticed anecdotally (a user complains, a "
                "dashboard times out) rather than being visible before they become a production issue."
            ),
            recommended_direction=(
                "Enable at least one: pg_stat_statements for aggregate query stats, auto_explain for "
                "plans on slow queries, or set log_min_duration_statement to a reasonable threshold."
            ),
        )
    ]
