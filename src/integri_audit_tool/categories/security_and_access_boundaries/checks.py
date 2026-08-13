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

    for row in queries.fetch_login_superuser_roles_without_connection_limit(conn):
        findings.append(
            Finding(
                check_slug="login-superuser-roles",
                title=f"Superuser role with no connection limit: {row['rolname']}",
                severity=Severity.LOW,
                observation=f"Role '{row['rolname']}' can log in as superuser with no connection limit (rolconnlimit = -1).",
                evidence="Detected via pg_roles.rolconnlimit = -1.",
                business_impact=(
                    "If this credential is ever shared across services or leaked, nothing at the database "
                    "level caps how many concurrent superuser connections it can open — amplifying both "
                    "accidental service-account sprawl and the blast radius of a credential compromise."
                ),
                recommended_direction="Set a connection limit appropriate to how this role is actually used (e.g. ALTER ROLE ... CONNECTION LIMIT n).",
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

    for row in queries.fetch_rls_enabled_without_force(conn):
        findings.append(
            Finding(
                check_slug="rls-enabled-without-policies",
                title=f"Row-level security policies don't apply to the table owner: {row['table_name']}",
                severity=Severity.LOW,
                observation=(
                    f"{row['schema_name']}.{row['table_name']} has row-level security enabled with "
                    "policies attached, but FORCE ROW LEVEL SECURITY is not set."
                ),
                evidence="Detected via pg_class.relrowsecurity AND NOT relforcerowsecurity, with matching rows in pg_policies.",
                business_impact=(
                    "Without FORCE, the table owner (and any role with BYPASSRLS) silently bypasses every "
                    "policy on this table — connections using the owner role see every row regardless of "
                    "what the policies say, which is easy to mistake for isolation actually working."
                ),
                recommended_direction="ALTER TABLE ... FORCE ROW LEVEL SECURITY, unless owner bypass is a deliberate, documented exception.",
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

    for row in queries.fetch_public_grants_on_pii_tables(conn):
        findings.append(
            Finding(
                check_slug="undocumented-pii-and-ssl",
                title=f"PUBLIC grant on a likely-PII table: {row['table_name']} ({row['privilege_type']})",
                severity=Severity.HIGH,
                observation=(
                    f"{row['schema_name']}.{row['table_name']} (has a PII-shaped column by name) grants "
                    f"{row['privilege_type']} to PUBLIC — every role in the database, not a scoped set."
                ),
                evidence="Heuristic name match on information_schema.columns + information_schema.table_privileges (grantee = 'PUBLIC').",
                business_impact=(
                    "A PUBLIC grant applies to every current and future role, including ones created "
                    "later for unrelated purposes — on a table that looks like it holds sensitive data, "
                    "this is a broad, easy-to-miss over-exposure rather than a scoped, intentional grant."
                ),
                recommended_direction="Revoke the PUBLIC grant and replace it with explicit grants to the specific roles that actually need access.",
            )
        )

    return findings


def check_authentication_method_strength(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 08.12 — how strong is the configured authentication (pg_hba.conf
    methods, password hashing algorithm)? New bullet (SOP merge, 2026-08-03) --
    doesn't map to any bullet in the original 11-bullet rubric, so it gets a
    fresh number past the original range, the same way schema_design's
    repeating-column-groups (01.07) and other SOP-merge checks did. Bullet 3
    (secrets stored outside version control) stays untouched/out_of_scope --
    that's a genuinely different question (where app config lives) from
    authentication method strength, not the same concern under a new name.
    """
    findings = []

    if queries.is_pg_hba_file_rules_readable(conn):
        for row in queries.fetch_pg_hba_rules(conn):
            if row["auth_method"] == "trust":
                severity = Severity.CRITICAL
            elif row["auth_method"] == "password":
                severity = Severity.HIGH
            else:
                continue
            findings.append(
                Finding(
                    check_slug="authentication-method-strength",
                    title=f"Weak pg_hba.conf auth method: {row['auth_method']} (line {row['line_number']})",
                    severity=severity,
                    observation=(
                        f"pg_hba.conf line {row['line_number']} allows database "
                        f"'{row['database']}', user '{row['user_name']}' from {row['address'] or 'local'} "
                        f"to authenticate via '{row['auth_method']}'."
                    ),
                    evidence="Detected via pg_hba_file_rules.",
                    business_impact=(
                        "'trust' allows connecting as the named user with no authentication at all — "
                        "anyone who can reach the port is in."
                        if row["auth_method"] == "trust"
                        else "'password' sends credentials in clear text unless the connection is "
                        "separately wrapped in SSL/TLS — interceptable on any untrusted network path."
                    ),
                    recommended_direction="Switch this rule to 'scram-sha-256' (with hostssl if the connection isn't otherwise encrypted).",
                )
            )
    else:
        findings.append(
            Finding(
                check_slug="authentication-method-strength",
                title="Could not assess pg_hba.conf: insufficient privilege",
                severity=Severity.INFORMATIONAL,
                observation=(
                    "pg_hba_file_rules is restricted to superuser by default, and the connection used "
                    "for this audit doesn't have that privilege — confirmed empirically that even broad "
                    "monitoring roles (pg_monitor, pg_read_all_settings) don't unlock it."
                ),
                evidence="Checked via has_table_privilege(current_user, 'pg_hba_file_rules', 'SELECT').",
                business_impact="pg_hba.conf authentication method strength can't be assessed from this connection.",
                recommended_direction="Re-run this check with a superuser connection, or have the client's DBA review pg_hba.conf directly.",
            )
        )

    encryption = queries.fetch_password_encryption_setting(conn)
    if encryption != "scram-sha-256":
        findings.append(
            Finding(
                check_slug="authentication-method-strength",
                title=f"Weak password hashing algorithm: {encryption}",
                severity=Severity.MEDIUM,
                observation=f"The server's password_encryption setting is '{encryption}', not 'scram-sha-256'.",
                evidence="Checked via pg_settings.",
                business_impact=(
                    "SCRAM-SHA-256 (the default since Postgres 14) is meaningfully stronger than the "
                    "legacy MD5 hashing scheme it replaced — new passwords hashed under a weaker "
                    "algorithm inherit that algorithm's weaknesses for as long as they're in use."
                ),
                recommended_direction="Set password_encryption = 'scram-sha-256' and have roles reset their passwords to pick up the new hash.",
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
