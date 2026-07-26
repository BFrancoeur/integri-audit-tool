"""Interprets category-7 catalog/statistics queries into Finding objects.

One function per rubric checklist bullet (see postgres-database-audit-rubric.md,
"7. Scale & Growth Readiness") — all five turn out to be assessable from
read-only catalog/statistics access, no row sampling needed. Each takes a
live connection + config and returns zero or more Findings. Kept separate
from queries.py so this interpretation logic is unit-testable against canned
row data without a live database.
"""

from __future__ import annotations

import psycopg

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import Finding, Severity

from . import queries

_HIGH_SLOW_QUERY_MS = 5000
_HIGH_BLOAT_RATIO = 0.5


def _pg_stat_statements_unavailable_finding(check_slug: str, bullet_summary: str) -> Finding:
    return Finding(
        check_slug=check_slug,
        title=f"Could not assess ({bullet_summary}): pg_stat_statements is not installed",
        severity=Severity.INFORMATIONAL,
        observation=(
            "The pg_stat_statements extension is not installed/enabled on this database, so measured "
            "query performance isn't available to inspect for this bullet."
        ),
        evidence="Checked via pg_extension.",
        business_impact="This aspect of scale readiness can't be assessed without pg_stat_statements.",
        recommended_direction=(
            "Enable pg_stat_statements (requires adding it to shared_preload_libraries and a restart, "
            "then CREATE EXTENSION pg_stat_statements) so a future audit can assess this."
        ),
    )


def _format_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def check_slow_queries(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 07.01 — are any operations already showing measured degraded performance?"""
    if not queries.is_pg_stat_statements_available(conn):
        return [_pg_stat_statements_unavailable_finding("slow-queries", "measured slow queries")]

    findings = []
    for row in queries.fetch_slow_queries(conn):
        severity = Severity.HIGH if row["mean_exec_time"] >= _HIGH_SLOW_QUERY_MS else Severity.MEDIUM
        findings.append(
            Finding(
                check_slug="slow-queries",
                title=f"Slow query: {row['mean_exec_time']:.0f}ms average over {row['calls']} calls",
                severity=severity,
                observation=(
                    f"Query averages {row['mean_exec_time']:.0f}ms (max {row['max_exec_time']:.0f}ms) "
                    f"across {row['calls']} observed calls: {row['query']}"
                ),
                evidence="Measured via pg_stat_statements, not hypothetical.",
                business_impact=(
                    "This is degraded performance happening now, at current row counts and load — not "
                    "a projection. It will only get worse as data volume grows."
                ),
                recommended_direction="Run EXPLAIN ANALYZE on this query to identify the bottleneck (missing index, sequential scan, etc.).",
            )
        )
    return findings


def check_largest_tables(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 07.02 — is table/index size growth tracked, with a stated volume threshold?"""
    rows = queries.fetch_largest_tables(conn)
    if not rows:
        return []

    lines = [f"{r['table_name']}: {_format_bytes(r['total_bytes'])}" for r in rows]
    return [
        Finding(
            check_slug="largest-tables",
            title=f"Current table footprint (top {len(rows)} by size)",
            severity=Severity.INFORMATIONAL,
            observation="Largest tables by total size (table + indexes + TOAST): " + "; ".join(lines),
            evidence="Measured via pg_total_relation_size() at audit time — a snapshot, not a trend.",
            business_impact=(
                "This tool can't tell you whether growth is tracked over time or whether a volume "
                "threshold is documented — that's a process question. This gives the auditor concrete "
                "current numbers to check against any stated thresholds."
            ),
            recommended_direction=(
                "If no volume threshold is documented for when the architecture needs to change "
                "(partitioning, read replicas, etc.), use these numbers as a starting baseline for one."
            ),
        )
    ]


def check_tenant_columns_without_rls(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 07.03 — does the architecture isolate tenant/category data access patterns?"""
    findings = []
    for row in queries.fetch_tenant_columns_without_rls(conn):
        findings.append(
            Finding(
                check_slug="tenant-columns-without-rls",
                title=f"Tenant-shaped table without row-level security: {row['table_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"{row['schema_name']}.{row['table_name']} has a column that looks like a tenant/"
                    "organization scope (tenant_id, org_id, etc.) but row-level security isn't enabled "
                    "on the table."
                ),
                evidence=(
                    "Heuristic name match on information_schema.columns + pg_class.relrowsecurity. "
                    "Doesn't prove queries leak across tenants — app-level filtering could still be "
                    "correct — only that Postgres's own isolation mechanism isn't engaged."
                ),
                business_impact=(
                    "Without RLS, tenant isolation depends entirely on every query in the codebase "
                    "remembering to filter by tenant — one missed WHERE clause is a cross-tenant data leak."
                ),
                recommended_direction=(
                    "Consider enabling row-level security with a policy scoped to the tenant column as a "
                    "database-enforced backstop, not just an application-layer convention."
                ),
            )
        )
    return findings


def check_high_bloat_tables_without_tuning(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 07.04 — is autovacuum tuned for the table's write/update pattern, or left at defaults?"""
    findings = []
    for row in queries.fetch_high_bloat_tables_without_tuning(conn):
        ratio = row["dead_tuple_ratio"]
        severity = Severity.HIGH if ratio >= _HIGH_BLOAT_RATIO else Severity.MEDIUM
        findings.append(
            Finding(
                check_slug="high-bloat-tables-without-tuning",
                title=f"High dead-tuple ratio on default autovacuum settings: {row['table_name']} ({ratio:.0%})",
                severity=severity,
                observation=(
                    f"{row['schema_name']}.{row['table_name']} has ~{row['n_dead_tup']} dead tuples "
                    f"against ~{row['n_live_tup']} live rows ({ratio:.0%}) and has no per-table "
                    "autovacuum overrides — it's running on cluster-wide defaults."
                ),
                evidence=(
                    "From pg_stat_user_tables + pg_class.reloptions. Can't detect cluster-wide ALTER "
                    "SYSTEM tuning this way, only per-table overrides."
                ),
                business_impact=(
                    "Bloat this high means autovacuum isn't keeping pace with this table's write/update "
                    "volume, which degrades index efficiency and can eventually trigger emergency "
                    "autovacuum-to-prevent-wraparound at the worst possible time."
                ),
                recommended_direction=(
                    "Lower autovacuum_vacuum_scale_factor / autovacuum_vacuum_cost_delay for this "
                    "specific table (via ALTER TABLE ... SET) rather than relying on defaults tuned for "
                    "an average table."
                ),
            )
        )
    return findings


def check_large_jsonb_on_hot_tables(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 07.05 — are large JSONB documents causing TOAST-related overhead on frequently-accessed rows?"""
    findings = []
    for row in queries.fetch_large_jsonb_on_hot_tables(conn):
        findings.append(
            Finding(
                check_slug="large-jsonb-on-hot-tables",
                title=f"Significant TOAST storage on a frequently-accessed table: {row['table_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"{row['schema_name']}.{row['table_name']} has a JSONB column and "
                    f"{_format_bytes(row['toast_bytes'])} of TOAST (out-of-line) storage, on a table "
                    f"accessed ~{row['access_count']} times (index + sequential scans)."
                ),
                evidence=(
                    "Measured directly via pg_total_relation_size() on the table's TOAST relation, not "
                    "inferred from pg_stats — average-width estimates shrink once a value is actually "
                    "TOASTed (down to a pointer), so they can't reliably detect this."
                ),
                business_impact=(
                    "Values large enough to be stored out-of-line require an extra fetch to detoast on "
                    "every access — real, repeated I/O cost on a table that's actually being read regularly."
                ),
                recommended_direction=(
                    "Consider whether the full document needs to be fetched on every read, or whether a "
                    "narrower projection / separate summary column would avoid detoasting on the hot path."
                ),
            )
        )
    return findings
