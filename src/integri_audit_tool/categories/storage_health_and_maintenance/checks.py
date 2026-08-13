"""Interprets Storage Health & Maintenance catalog/statistics queries into
Finding objects.

One function per rubric checklist bullet (see postgres-database-audit-rubric.md,
"Storage Health & Maintenance"). Each takes a live connection + config and
returns zero or more Findings. Kept separate from queries.py so this
interpretation logic is unit-testable against canned row data without a live
database.
"""

from __future__ import annotations

import psycopg

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import Finding, Severity

from . import queries


def _format_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _bloat_severity(ratio: float) -> Severity:
    return Severity.HIGH if ratio >= queries.BLOAT_REMEDIATE_THRESHOLD else Severity.MEDIUM


def check_table_bloat(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Storage Health 1 — is table bloat within a healthy range, measured
    directly where possible?"""
    if queries.is_pgstattuple_available(conn):
        rows = queries.fetch_table_bloat_measured(conn)
        measurement_method = "measured"
        evidence_source = "Measured via pgstattuple_approx() (free-space-map estimate, not a full heap scan)."
    else:
        rows = queries.fetch_table_bloat_estimated(conn)
        measurement_method = "estimated"
        evidence_source = (
            "Estimated from pg_stat_user_tables dead-tuple counts (pgstattuple extension not installed "
            "— install it for a direct measurement)."
        )

    findings = []
    for row in rows:
        ratio = row["dead_tuple_ratio"]
        findings.append(
            Finding(
                check_slug="table-bloat",
                title=f"Table bloat: {row['table_name']} ({ratio:.0%} dead tuples)",
                severity=_bloat_severity(ratio),
                observation=f"{row['schema_name']}.{row['table_name']} is ~{ratio:.0%} dead tuples by volume.",
                evidence=evidence_source,
                business_impact=(
                    "Bloat this high means autovacuum isn't keeping pace with this table's write/update "
                    "volume, degrading index efficiency and wasting storage until it's reclaimed."
                ),
                recommended_direction=(
                    "Investigate autovacuum settings for this table (scale_factor/cost_delay) if the "
                    f"ratio is under {queries.BLOAT_REMEDIATE_THRESHOLD:.0%}; consider a manual VACUUM "
                    "or tuning at or above it."
                ),
                measurement_method=measurement_method,
            )
        )
    return findings


def check_index_bloat(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Storage Health 2 — is B-tree index bloat within a healthy range?"""
    if not queries.is_pgstattuple_available(conn):
        return [
            Finding(
                check_slug="index-bloat",
                title="Could not assess index bloat: pgstattuple is not installed",
                severity=Severity.INFORMATIONAL,
                observation=(
                    "The pgstattuple extension is not installed, so index bloat can't be directly "
                    "measured. No non-extension fallback is used here — a reliable B-tree bloat estimate "
                    "without pgstattuple is fragile enough that an honest 'not assessed' is preferable "
                    "to a heuristic number that might mislead."
                ),
                evidence="Checked via pg_extension.",
                business_impact="Index bloat can't be assessed without pgstattuple.",
                recommended_direction="Install the pgstattuple extension (no shared_preload_libraries entry needed) so a future audit can assess this.",
            )
        ]

    findings = []
    for row in queries.fetch_index_bloat_measured(conn):
        ratio = row["estimated_bloat_ratio"]
        findings.append(
            Finding(
                check_slug="index-bloat",
                title=f"Index bloat: {row['index_name']} on {row['table_name']} ({ratio:.0%})",
                severity=_bloat_severity(ratio),
                observation=(
                    f"Index '{row['index_name']}' on {row['schema_name']}.{row['table_name']} is "
                    f"~{ratio:.0%} bloated (estimated from leaf-page density)."
                ),
                evidence="Measured via pgstatindex() -- B-tree indexes only.",
                business_impact=(
                    "A bloated index wastes storage and I/O on every scan that uses it, without "
                    "providing any additional query coverage."
                ),
                recommended_direction="REINDEX CONCURRENTLY this index once maintenance-window access is confirmed.",
                measurement_method="measured",
            )
        )
    return findings


def check_index_to_table_size_ratio(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Storage Health 3 — is any index larger than the table it indexes?"""
    findings = []
    for row in queries.fetch_index_to_table_size_ratio_outliers(conn):
        ratio = row["index_bytes"] / row["table_bytes"]
        findings.append(
            Finding(
                check_slug="index-to-table-size-ratio",
                title=f"Index larger than its table: {row['index_name']} on {row['table_name']}",
                severity=Severity.LOW,
                observation=(
                    f"Index '{row['index_name']}' ({_format_bytes(row['index_bytes'])}) is larger than "
                    f"{row['schema_name']}.{row['table_name']} itself ({_format_bytes(row['table_bytes'])}, "
                    f"{ratio:.1f}x)."
                ),
                evidence="Measured via pg_relation_size() on both the index and its table.",
                business_impact=(
                    "An index bigger than its own table is a red flag worth investigating on its own — "
                    "it may indicate bloat, an over-broad expression index, or a column choice with "
                    "poor compressibility relative to the table's row width."
                ),
                recommended_direction="Review the index definition and consider whether a narrower index would serve the same queries.",
            )
        )
    return findings


def check_large_toast_on_hot_tables(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Storage Health 4 — are large values causing TOAST-related overhead on frequently-accessed rows?"""
    findings = []
    for row in queries.fetch_large_toast_on_hot_tables(conn):
        findings.append(
            Finding(
                check_slug="large-toast-on-hot-tables",
                title=f"Significant TOAST storage on a frequently-accessed table: {row['table_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"{row['schema_name']}.{row['table_name']} has a large jsonb/text/bytea column and "
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
                    "Consider whether the full value needs to be fetched on every read, or whether a "
                    "narrower projection / separate summary column would avoid detoasting on the hot path."
                ),
            )
        )
    return findings


def check_toast_storage_strategy(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Storage Health 5 — is TOAST storage strategy (EXTENDED vs. EXTERNAL) appropriate for the access pattern?"""
    findings = []
    for row in queries.fetch_toast_storage_strategy_on_large_columns(conn):
        findings.append(
            Finding(
                check_slug="toast-storage-strategy",
                title=f"EXTENDED (compressed) storage on a large column: {row['table_name']}.{row['column_name']}",
                severity=Severity.INFORMATIONAL,
                observation=(
                    f"{row['schema_name']}.{row['table_name']}.{row['column_name']} uses EXTENDED "
                    "storage (compressed, out-of-line) and belongs to a table with meaningful TOAST usage."
                ),
                evidence=(
                    "Detected via pg_attribute.attstorage. EXTENDED is Postgres's own default for "
                    "jsonb/text/bytea columns, not inherently wrong — this is informational context for "
                    "the auditor to weigh against the actual access pattern, which this tool can't "
                    "confirm without query-level analysis."
                ),
                business_impact=(
                    "Frequent partial reads (e.g. extracting one key from a large JSON document) against "
                    "EXTENDED storage pay a decompression cost on every access; EXTERNAL storage trades "
                    "away compression for cheaper partial reads."
                ),
                recommended_direction=(
                    "If this column is frequently read partially rather than in full, consider "
                    "ALTER COLUMN ... SET STORAGE EXTERNAL and measure the difference."
                ),
            )
        )
    return findings


def check_autovacuum_explicitly_disabled(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Storage Health 6 — is autovacuum explicitly disabled on any table?"""
    findings = []
    for row in queries.fetch_autovacuum_explicitly_disabled(conn):
        findings.append(
            Finding(
                check_slug="autovacuum-explicitly-disabled",
                title=f"Autovacuum explicitly disabled: {row['table_name']}",
                severity=Severity.HIGH,
                observation=f"{row['schema_name']}.{row['table_name']} has autovacuum_enabled=false set explicitly.",
                evidence="Detected via pg_class.reloptions.",
                business_impact=(
                    "This is a deliberate override, not just an untuned default — dead tuples on this "
                    "table will never be reclaimed automatically, and bloat will grow unbounded until "
                    "someone manually intervenes."
                ),
                recommended_direction="Confirm this was intentional (e.g. a manually-managed maintenance window); if not, remove the override.",
            )
        )
    return findings


def check_xmin_horizon_risk(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Storage Health 7 — is a long-running transaction or abandoned replication
    slot holding back the xmin horizon (the common root cause of "why is
    everything bloated")?"""
    findings = []
    for row in queries.fetch_long_running_transactions(conn):
        findings.append(
            Finding(
                check_slug="xmin-horizon-risk",
                title=f"Long-running transaction: pid {row['pid']} open {row['transaction_duration']}",
                severity=Severity.HIGH,
                observation=(
                    f"Session pid {row['pid']} (user '{row['usename']}', app '{row['application_name']}') "
                    f"has an open transaction lasting {row['transaction_duration']}, last query: "
                    f"{row['last_query']}"
                ),
                evidence=f"Detected via pg_stat_activity (threshold: {queries.LONG_RUNNING_TRANSACTION_THRESHOLD_MINUTES} minutes).",
                business_impact=(
                    "A long-running transaction holds back the xmin horizon cluster-wide — autovacuum "
                    "can't reclaim any dead tuple newer than this transaction's start, silently defeating "
                    "vacuum across the whole database, not just this session's own tables."
                ),
                recommended_direction="Investigate why this session is still open; terminate it if abandoned.",
            )
        )
    for row in queries.fetch_stalled_replication_slots(conn):
        retained = row["retained_bytes"]
        retained_desc = _format_bytes(retained) if retained is not None else "unknown"
        status = "inactive" if not row["active"] else "active but far behind"
        findings.append(
            Finding(
                check_slug="xmin-horizon-risk",
                title=f"Replication slot holding back WAL: {row['slot_name']} ({status})",
                severity=Severity.HIGH,
                observation=f"Slot '{row['slot_name']}' ({row['slot_type']}) is {status}, retaining ~{retained_desc} of WAL.",
                evidence="Detected via pg_replication_slots + pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn).",
                business_impact=(
                    "An abandoned or far-behind replication slot prevents WAL from being recycled and, "
                    "like a long-running transaction, can hold back the xmin horizon and defeat vacuum "
                    "cluster-wide until it's dropped or catches up."
                ),
                recommended_direction="Confirm this slot still has a live consumer; drop it if abandoned.",
            )
        )
    return findings
