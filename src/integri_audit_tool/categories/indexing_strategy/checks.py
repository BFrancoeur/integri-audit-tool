"""Interprets category-3 catalog queries into Finding objects.

One function per rubric checklist bullet (see postgres-database-audit-rubric.md,
"3. Indexing Strategy"). Each takes a live connection + config and returns zero
or more Findings. Kept separate from queries.py so this interpretation logic is
unit-testable against canned row data without a live database.
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


def _unused_index_findings(conn: psycopg.Connection) -> list[Finding]:
    findings = []
    for row in queries.fetch_unused_indexes(conn):
        findings.append(
            Finding(
                check_slug="unused-indexes",
                title=f"Unused index: {row['index_name']} on {row['table_name']}",
                severity=Severity.LOW,
                observation=(
                    f"Index '{row['index_name']}' on {row['schema_name']}.{row['table_name']} "
                    "has recorded zero scans and is not backing a primary key or unique constraint."
                ),
                evidence=f"idx_scan=0, index size={row['index_size_bytes']} bytes (pg_stat_user_indexes).",
                business_impact=(
                    "Unused indexes add write overhead on every INSERT/UPDATE/DELETE to the table "
                    "and consume storage without providing any read benefit."
                ),
                recommended_direction=(
                    "Confirm the index isn't used by infrequent batch/reporting queries "
                    "(check over a full reporting cycle, not just recent activity), then drop it."
                ),
            )
        )
    return findings


def _unindexed_foreign_key_findings(conn: psycopg.Connection) -> list[Finding]:
    findings = []
    for row in queries.fetch_unindexed_foreign_keys(conn):
        findings.append(
            Finding(
                check_slug="unused-indexes",
                title=f"Unindexed foreign key: {row['table_name']}.{row['column_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"Column '{row['column_name']}' on {row['schema_name']}.{row['table_name']} has a "
                    f"declared foreign key ('{row['constraint_name']}') but no index with it as the "
                    "leading column."
                ),
                evidence="Detected via pg_constraint + pg_index (no matching leading-column index).",
                business_impact=(
                    "Every DELETE or UPDATE of the referenced parent row forces Postgres to scan this "
                    "entire table to check for dependent rows, since there's no index to look them up "
                    "by — a near-automatic full table scan on the hot path of parent-row changes."
                ),
                recommended_direction=f"Add an index with '{row['column_name']}' as the leading column.",
            )
        )
    return findings


def _seq_scan_heavy_table_findings(conn: psycopg.Connection) -> list[Finding]:
    findings = []
    for row in queries.fetch_seq_scan_heavy_tables(conn):
        findings.append(
            Finding(
                check_slug="unused-indexes",
                title=f"Sequential-scan-heavy table: {row['table_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"{row['schema_name']}.{row['table_name']} ({_format_bytes(row['table_bytes'])}) has "
                    f"been sequentially scanned {row['seq_scan']} times ({row['seq_tup_read']} rows read) "
                    f"vs. {row['idx_scan']} index scans."
                ),
                evidence="Measured via pg_stat_user_tables (seq_scan/idx_scan counters), not query-log sampling.",
                business_impact=(
                    "A table this size being scanned sequentially more often than it's indexed into "
                    "suggests queries are filtering on a column with no supporting index — each scan "
                    "reads the whole table instead of the rows that actually match."
                ),
                recommended_direction=(
                    "Review the table's common query filters (WHERE/JOIN/ORDER BY columns) via "
                    "EXPLAIN ANALYZE and add an index for whichever isn't currently covered."
                ),
            )
        )
    return findings


def _composite_index_order_mismatch_findings(conn: psycopg.Connection) -> list[Finding]:
    if not queries.is_pg_stat_statements_available(conn):
        return []

    findings = []
    for row in queries.fetch_composite_indexes(conn):
        columns = row["index_columns"]
        leading_column, second_column = columns[0], columns[1]
        matched_count = queries.fetch_queries_mentioning_second_column_not_leading(
            conn, row["table_name"], leading_column, second_column
        )
        if matched_count == 0:
            continue
        findings.append(
            Finding(
                check_slug="unused-indexes",
                title=f"Possible composite index column-order mismatch: {row['index_name']}",
                severity=Severity.LOW,
                observation=(
                    f"Index '{row['index_name']}' on {row['schema_name']}.{row['table_name']} leads "
                    f"with '{leading_column}', but {matched_count} observed statement(s) filter on "
                    f"'{second_column}' without mentioning '{leading_column}' at all."
                ),
                evidence=(
                    "Heuristic text match on pg_stat_statements query text (substring search for column "
                    "names, not a parsed predicate list) — can both miss real mismatches and produce "
                    "false positives; treat as a lead to investigate with EXPLAIN, not a confirmed defect."
                ),
                business_impact=(
                    "A composite B-tree index can only be used efficiently when its leading column is "
                    "constrained — a query filtering only on a trailing column gets little or no benefit "
                    "from this index and likely falls back to a sequential scan."
                ),
                recommended_direction=(
                    f"Confirm with EXPLAIN whether queries filtering on '{second_column}' alone are "
                    f"using this index; if not, consider a separate index led by '{second_column}'."
                ),
            )
        )
    return findings


def check_unused_indexes(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 03.01 — do query patterns match the indexes that exist?"""
    return [
        *_unused_index_findings(conn),
        *_unindexed_foreign_key_findings(conn),
        *_seq_scan_heavy_table_findings(conn),
        *_composite_index_order_mismatch_findings(conn),
    ]


def check_gin_usage(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 03.02 — is GIN used appropriately for JSONB containment / full-text search?"""
    findings = []
    for row in queries.fetch_jsonb_columns_without_gin(conn):
        findings.append(
            Finding(
                check_slug="gin-usage",
                title=f"JSONB column without a GIN index: {row['table_name']}.{row['column_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"Column '{row['column_name']}' on {row['schema_name']}.{row['table_name']} is "
                    "JSONB but no GIN index was found covering it."
                ),
                evidence="Detected via information_schema.columns + pg_indexes (heuristic text match on indexdef).",
                business_impact=(
                    "Containment (@>) or key-existence queries against this column will require a "
                    "sequential scan, which won't scale as the table grows."
                ),
                recommended_direction=(
                    "If this column is queried with @> or key-existence operators, add a GIN index "
                    "(jsonb_path_ops for containment-only, default jsonb_ops if key-existence queries are needed)."
                ),
            )
        )
    return findings


def check_redundant_indexes(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 03.04 — are there redundant or overlapping indexes?"""
    findings = []
    for row in queries.fetch_indexes_sharing_leading_column(conn):
        index_list = ", ".join(row["index_names"])
        findings.append(
            Finding(
                check_slug="redundant-indexes",
                title=f"Possible overlapping indexes on {row['table_name']} ({row['leading_column']})",
                severity=Severity.LOW,
                observation=(
                    f"{len(row['index_names'])} indexes on {row['table_name']} share the same leading "
                    f"column '{row['leading_column']}': {index_list}."
                ),
                evidence="; ".join(row["index_defs"]),
                business_impact=(
                    "Overlapping indexes are maintained redundantly on every write without adding "
                    "distinct query coverage, increasing write amplification and storage cost."
                ),
                recommended_direction=(
                    "Review whether one index's columns are a strict subset of another's; if so, "
                    "the narrower index is usually safe to drop."
                ),
            )
        )
    return findings


def _selectivity_ratio(n_distinct: float, n_live_tup: int) -> float | None:
    """Resolves pg_stats.n_distinct's dual sign convention (positive = absolute
    count, negative = fraction of rows) into a single 0-1 selectivity ratio --
    same logic as data_quality_and_integrity's near-unique check, duplicated
    rather than imported since each category module is self-contained."""
    if n_live_tup <= 0:
        return None
    if n_distinct < 0:
        return min(-n_distinct, 1.0)
    return min(n_distinct / n_live_tup, 1.0)


def check_high_selectivity_columns_without_index(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 03.03 — are B-tree indexes present on high-selectivity columns
    used in equality/range filters, joins, and sort/order-by clauses?"""
    findings = []
    for row in queries.fetch_high_selectivity_columns_without_index(conn):
        ratio = _selectivity_ratio(row["n_distinct"], row["n_live_tup"])
        if ratio is None or ratio < queries.HIGH_SELECTIVITY_RATIO_THRESHOLD:
            continue
        findings.append(
            Finding(
                check_slug="high-selectivity-columns-without-index",
                title=f"High-selectivity column with no index: {row['table_name']}.{row['column_name']}",
                severity=Severity.LOW,
                observation=(
                    f"Column '{row['column_name']}' on {row['schema_name']}.{row['table_name']} is "
                    f"~{ratio:.0%} distinct across ~{row['n_live_tup']} rows and has no index covering it "
                    "at all."
                ),
                evidence=(
                    "From pg_stats.n_distinct (estimate from the last ANALYZE), cross-checked against "
                    "pg_index for any covering index — doesn't confirm this column is actually used in a "
                    "WHERE/JOIN/ORDER BY clause, only that it's a plausible candidate by cardinality alone."
                ),
                business_impact=(
                    "If this column is used for equality/range filtering, joins, or sorting, every such "
                    "query falls back to a sequential scan with no supporting index."
                ),
                recommended_direction=(
                    "Confirm via EXPLAIN ANALYZE or query logs whether this column is actually filtered, "
                    "joined, or sorted on; if so, add a B-tree index."
                ),
            )
        )
    return findings


def check_unpromoted_jsonb_range_queries(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 03.05 — are range queries (numeric or date) being run against
    JSONB fields with no promoted column?"""
    if not queries.is_pg_stat_statements_available(conn):
        return []

    findings = []
    for col in queries.fetch_jsonb_columns(conn):
        matched_count = queries.fetch_jsonb_range_query_candidate_count(conn, col["column_name"])
        if matched_count == 0:
            continue
        findings.append(
            Finding(
                check_slug="unpromoted-jsonb-range-queries",
                title=f"Possible unpromoted JSONB range query: {col['table_name']}.{col['column_name']}",
                severity=Severity.LOW,
                observation=(
                    f"{matched_count} observed statement(s) extract a value from "
                    f"{col['schema_name']}.{col['table_name']}.{col['column_name']} (via ->> or #>>) "
                    "alongside a comparison operator or BETWEEN, with no promoted column found for it."
                ),
                evidence=(
                    "Heuristic text match on pg_stat_statements query text (substring search, not a "
                    "parsed predicate list) — can both miss real range queries and produce false "
                    "positives; treat as a lead to investigate with EXPLAIN, not a confirmed defect."
                ),
                business_impact=(
                    "A numeric or date range comparison against a JSONB-extracted value can't use a "
                    "B-tree index the way a promoted, properly-typed column could — every such query "
                    "falls back to scanning and casting every row."
                ),
                recommended_direction=(
                    "If this key is genuinely range-queried, promote it to its own typed column (generated "
                    "column or trigger-maintained) with a supporting index."
                ),
            )
        )
    return findings


def check_excessive_indexing_write_amplification(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 03.06 — is there an index maintenance concern (high write volume
    tables with excessive indexing, causing write amplification)?"""
    findings = []
    for row in queries.fetch_high_write_tables_with_many_indexes(conn):
        findings.append(
            Finding(
                check_slug="excessive-indexing-write-amplification",
                title=f"High-write table with many indexes: {row['table_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"{row['schema_name']}.{row['table_name']} has recorded {row['write_count']} "
                    f"lifetime inserts/updates/deletes and carries {row['index_count']} indexes."
                ),
                evidence="Measured via pg_stat_user_tables (write counters) and pg_index (index count).",
                business_impact=(
                    "Every write to this table has to maintain all of its indexes, not just the row "
                    "itself — a high write volume combined with an unusually large number of indexes "
                    "means real, ongoing write overhead, not a one-time cost."
                ),
                recommended_direction=(
                    "Review each index's actual usage (see the unused-indexes findings above) and confirm "
                    "every remaining one earns its write-time cost on this specific table."
                ),
            )
        )
    return findings


def check_underused_partial_indexes(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 03.07 — are partial indexes or expression indexes used where
    they'd meaningfully narrow index size (e.g., indexing only WHERE active = true)?"""
    findings = []
    for row in queries.fetch_non_partial_indexes_on_flag_columns(conn):
        findings.append(
            Finding(
                check_slug="underused-partial-indexes",
                title=f"Non-partial index on a flag-shaped column: {row['index_name']}",
                severity=Severity.LOW,
                observation=(
                    f"Index '{row['index_name']}' on {row['schema_name']}.{row['table_name']}"
                    f"({row['column_name']}) is a full index with no WHERE clause, but leads with a "
                    "boolean or status/flag-shaped column."
                ),
                evidence=row["index_def"],
                business_impact=(
                    "If this column's values are heavily skewed toward one value (the common case for "
                    "active/enabled/deleted-style flags), a full index wastes space and write overhead "
                    "indexing the majority value that's rarely what queries filter for."
                ),
                recommended_direction=(
                    "Check the column's actual value distribution; if skewed, replace this with a partial "
                    "index scoped to the minority value actually being filtered on."
                ),
            )
        )
    return findings
