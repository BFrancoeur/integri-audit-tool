"""Interprets category-11 catalog queries into Finding objects.

One function per rubric checklist bullet (see postgres-database-audit-rubric.md,
"11. Documentation & Institutional Knowledge") that's assessable from
read-only catalog access. 11.04 (a change log/migration history legible as a
narrative, not just a list of diffs) is declared in `out_of_scope` in
__init__.py — assessing whether migration entries read as a coherent story
vs. bare version numbers would mean parsing arbitrary content across a dozen
different migration tools' table schemas, not something this tool can do
reliably. Each function here takes a live connection + config and returns
zero or more Findings. Kept separate from queries.py so this interpretation
logic is unit-testable against canned row data without a live database.
"""

from __future__ import annotations

import psycopg

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import Finding, Severity

from . import queries


def check_table_documentation_coverage(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 11.01 — is the schema documented anywhere outside the schema itself?"""
    coverage = queries.fetch_table_documentation_coverage(conn)
    if coverage["total_tables"] == 0 or coverage["documented_tables"] > 0:
        return []

    return [
        Finding(
            check_slug="table-documentation-coverage",
            title="No table-level documentation found in the schema",
            severity=Severity.LOW,
            observation=(
                f"None of the {coverage['total_tables']} user tables have a COMMENT ON TABLE set."
            ),
            evidence=(
                "Checked via obj_description() over pg_class — this only sees documentation stored "
                "inside Postgres itself. An ERD, data dictionary, or README living outside the database "
                "would be invisible to this check either way, so this isn't proof nothing is documented "
                "anywhere, only that nothing is documented *here*."
            ),
            business_impact=(
                "Without any documentation this tool can see, and absent confirmation of external docs, "
                "a new engineer's fastest path to understanding the schema is reading application code or "
                "asking someone who already knows it."
            ),
            recommended_direction="Confirm whether external documentation (wiki, ERD, README) exists and is current; if not, COMMENT ON TABLE is a low-effort starting point that travels with the schema.",
        )
    ]


def check_undocumented_jsonb_column_rationale(
    conn: psycopg.Connection, config: AuditConfig
) -> list[Finding]:
    """Rubric 11.02 — is there a record of why key architectural decisions (e.g. JSONB) were made?"""
    findings = []
    for row in queries.fetch_undocumented_jsonb_columns(conn):
        findings.append(
            Finding(
                check_slug="undocumented-jsonb-column-rationale",
                title=f"Undocumented JSONB column: {row['table_name']}.{row['column_name']}",
                severity=Severity.LOW,
                observation=(
                    f"Column '{row['column_name']}' on {row['schema_name']}.{row['table_name']} is "
                    "JSONB with no column comment explaining what it's for or why JSONB was chosen."
                ),
                evidence="Checked via col_description() — same visibility limits as 11.01: this only sees documentation stored inside Postgres.",
                business_impact=(
                    "JSONB is exactly the kind of choice that benefits from a recorded 'why' — what's "
                    "expected to vary, what's deliberately kept flexible. Without it, that reasoning "
                    "exists only in whoever made the decision's head."
                ),
                recommended_direction="Add a COMMENT ON COLUMN noting what this JSONB column is for and why it isn't normalized further.",
            )
        )
    return findings


def check_jsonb_without_schema_registry(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 11.03 — would a new engineer understand JSONB structure without reverse-engineering it?"""
    presence = queries.fetch_jsonb_and_registry_presence(conn)
    if not presence["has_jsonb_columns"] or presence["has_registry_table"]:
        return []

    return [
        Finding(
            check_slug="jsonb-without-schema-registry",
            title="JSONB columns exist with no schema/registry table found",
            severity=Severity.LOW,
            observation=(
                "This database has JSONB columns but no table matching common naming for a JSONB "
                "structure registry (e.g. attribute_definitions, schema_registry, field_registry)."
            ),
            evidence=(
                "Heuristic table-name match — a team documenting JSONB structure a different way (an "
                "external schema file, a shared library's type definitions) would also produce this "
                "result, so this isn't proof no governance exists, just an absence of the most common "
                "in-database signal that it does."
            ),
            business_impact=(
                "Without a documented registry of valid keys/types, a new engineer's only way to learn "
                "the actual shape of these JSONB columns is reverse-engineering it from production data "
                "— slow, error-prone, and easy to get wrong for keys that are rare or newly added."
            ),
            recommended_direction="Document the expected JSONB structure somewhere durable — a registry table, a shared schema file, or at minimum thorough column comments (see 11.02).",
        )
    ]
