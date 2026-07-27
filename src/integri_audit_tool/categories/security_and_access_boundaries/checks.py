"""Interprets category-8 catalog queries into Finding objects.

One function per rubric checklist bullet (see postgres-database-audit-rubric.md,
"8. Security & Access Boundaries") that's assessable from read-only catalog
access. 08.03 (secrets stored outside version control/application code) is
declared in `out_of_scope` in __init__.py instead — nothing about where an
application's config lives is visible from inside the database it connects
to. Each function here takes a live connection + config and returns zero or
more Findings. Kept separate from queries.py so this interpretation logic is
unit-testable against canned row data without a live database.
"""

from __future__ import annotations

import psycopg

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import Finding, Severity

from . import queries


def check_login_superuser_roles(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 08.01 — are database roles scoped by least privilege?"""
    findings = []
    for row in queries.fetch_login_superuser_roles(conn):
        findings.append(
            Finding(
                check_slug="login-superuser-roles",
                title=f"Login role with superuser: {row['rolname']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"Role '{row['rolname']}' can log in and has SUPERUSER. Every bootstrap Postgres "
                    "install has at least one such role — the question is whether the application "
                    "actually connects as this role day-to-day rather than a scoped app role."
                ),
                evidence="Detected via pg_roles.rolcanlogin AND pg_roles.rolsuper.",
                business_impact=(
                    "A superuser connection bypasses every permission check in the database, including "
                    "row-level security — a bug or injection in application code has unlimited blast radius."
                ),
                recommended_direction=(
                    "Confirm whether this role is used for routine application traffic; if so, create a "
                    "scoped app role with only the grants it needs and reserve superuser for admin tasks."
                ),
            )
        )
    return findings


def check_rls_enabled_without_policies(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 08.02 — is row-level security in use where multi-tenant isolation is required?"""
    findings = []
    for row in queries.fetch_rls_enabled_without_policies(conn):
        findings.append(
            Finding(
                check_slug="rls-enabled-without-policies",
                title=f"Row-level security enabled with no policies: {row['table_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"{row['schema_name']}.{row['table_name']} has row-level security enabled "
                    "(ENABLE ROW LEVEL SECURITY) but no policies are defined for it."
                ),
                evidence="Detected via pg_class.relrowsecurity with no matching rows in pg_policies.",
                business_impact=(
                    "With RLS enabled and zero policies, non-owner roles see no rows at all by default — "
                    "this either silently breaks the application (if unintentional) or means the table's "
                    "isolation is actually enforced elsewhere (table owner bypass, superuser access), not "
                    "by the RLS that appears to be protecting it."
                ),
                recommended_direction="Add the intended CREATE POLICY statements, or disable RLS if isolation is deliberately handled elsewhere.",
            )
        )
    return findings


def check_undocumented_pii_and_ssl(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 08.04 — is sensitive data flagged, and encrypted in transit appropriately?"""
    findings = []

    for row in queries.fetch_undocumented_pii_columns(conn):
        findings.append(
            Finding(
                check_slug="undocumented-pii-and-ssl",
                title=f"Undocumented likely-PII column: {row['table_name']}.{row['column_name']}",
                severity=Severity.LOW,
                observation=(
                    f"Column '{row['column_name']}' on {row['schema_name']}.{row['table_name']} looks "
                    "like it holds sensitive data (name heuristic) but has no column comment/description."
                ),
                evidence="Heuristic name match on pg_attribute.attname; documentation checked via col_description().",
                business_impact=(
                    "Without any documented flag, there's nothing in the schema itself telling a future "
                    "engineer (or a compliance review) that this column needs special handling — masking, "
                    "access restriction, retention limits."
                ),
                recommended_direction="Add a COMMENT ON COLUMN documenting what's stored and any handling requirements, even if the tooling for a fuller classification system doesn't exist yet.",
            )
        )

    ssl_setting = queries.fetch_ssl_setting(conn)
    if ssl_setting != "on":
        findings.append(
            Finding(
                check_slug="undocumented-pii-and-ssl",
                title="Server-side SSL is not enabled",
                severity=Severity.MEDIUM,
                observation=f"The server's `ssl` setting is '{ssl_setting}', not 'on'.",
                evidence="Checked via pg_settings.",
                business_impact=(
                    "Without SSL, connections (including credentials and query data) travel in "
                    "plaintext — trivially interceptable on any network path between app and database "
                    "that isn't otherwise fully trusted and isolated."
                ),
                recommended_direction="Enable SSL on the server and require it for client connections (ssl = on, plus hostssl entries in pg_hba.conf).",
            )
        )

    return findings


def check_audit_trail_availability(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 08.05 — are audit logs available for who changed what?"""
    status = queries.fetch_audit_trail_status(conn)
    if status["pgaudit_enabled"] or status["log_statement"] != "none":
        return []

    return [
        Finding(
            check_slug="audit-trail-availability",
            title="No audit trail mechanism detected",
            severity=Severity.MEDIUM,
            observation=(
                "Neither pgaudit is installed nor is log_statement configured to capture anything "
                f"(current value: {status['log_statement']!r}); log_connections is "
                f"{status['log_connections']!r}."
            ),
            evidence="Checked via pg_extension and pg_settings.",
            business_impact=(
                "Without an audit trail, answering 'who changed this row and when' after an incident is "
                "often impossible — change history is unrecoverable rather than just inconvenient to get to."
            ),
            recommended_direction="Install pgaudit for detailed statement-level auditing, or at minimum set log_statement to 'mod' or 'all' for a baseline record.",
        )
    ]


def check_superuser_roles_without_expiration(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 08.06 — are elevated access grants time-boxed with automatic expiration?"""
    findings = []
    for row in queries.fetch_superuser_roles_without_expiration(conn):
        findings.append(
            Finding(
                check_slug="superuser-roles-without-expiration",
                title=f"Superuser role with no expiration: {row['rolname']}",
                severity=Severity.MEDIUM,
                observation=f"Role '{row['rolname']}' has SUPERUSER and no VALID UNTIL expiration set.",
                evidence="Detected via pg_roles.rolsuper AND pg_roles.rolvaliduntil IS NULL.",
                business_impact=(
                    "Elevated access with no expiration relies entirely on someone remembering to revoke "
                    "it later — for permanent admin accounts that's expected, but for anything granted for "
                    "a contractor, an incident, or a one-off task, it tends to just stay granted indefinitely."
                ),
                recommended_direction=(
                    "For permanent admin roles this may be intentional — confirm and move on. For any "
                    "role granted for temporary/incident access, set VALID UNTIL to auto-expire it."
                ),
            )
        )
    return findings
