"""Raw catalog SQL for the Security & Access Boundaries category.

Everything here reads role/policy/setting catalogs that any connected role
can see (pg_roles, pg_policies, pg_settings, pg_extension) — no row sampling,
no pg_stat_statements dependency.

Note on overlap with category 7: rubric bullet 08.02 ("is RLS in use where
multi-tenant isolation is required") covers similar ground to category 7's
07.03 ("tenant-shaped columns without RLS enabled"). Rather than duplicate
that check here, 08.02 looks at a different, complementary failure mode: a
table where RLS *is* enabled but has zero policies attached — a common
misconfiguration (ENABLE ROW LEVEL SECURITY without ever running CREATE
POLICY), not "isolation was never attempted" like 07.03 covers.

Kept separate from checks.py so the interpretation logic (checks.py) can be
unit-tested against canned row data without a live database, while these
queries are the thing an integration test validates against real Postgres.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

# Heuristic name match on common PII/sensitive-data column names.
PII_COLUMN_NAME_PATTERN = r"(email|ssn|social_security|password|credit.?card|phone|date_of_birth|passport|ip_address)"

_LOGIN_SUPERUSER_ROLES_SQL = """
    SELECT rolname
    FROM pg_roles
    WHERE rolcanlogin
      AND rolsuper
    ORDER BY rolname;
"""

_RLS_ENABLED_WITHOUT_POLICIES_SQL = """
    SELECT
        n.nspname AS schema_name,
        c.relname AS table_name
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'r'
      AND c.relrowsecurity
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND NOT EXISTS (
          SELECT 1 FROM pg_policies p
          WHERE p.schemaname = n.nspname AND p.tablename = c.relname
      )
    ORDER BY n.nspname, c.relname;
"""

_UNDOCUMENTED_PII_COLUMNS_SQL = """
    SELECT
        n.nspname AS schema_name,
        t.relname AS table_name,
        a.attname AS column_name
    FROM pg_attribute a
    JOIN pg_class t ON t.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE t.relkind = 'r'
      AND a.attnum > 0
      AND NOT a.attisdropped
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND a.attname ~* %(pii_pattern)s
      AND col_description(t.oid, a.attnum) IS NULL
    ORDER BY n.nspname, t.relname, a.attname;
"""

_SSL_SETTING_SQL = """
    SELECT setting FROM pg_settings WHERE name = 'ssl';
"""

_AUDIT_TRAIL_STATUS_SQL = """
    SELECT
        EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pgaudit') AS pgaudit_enabled,
        (SELECT setting FROM pg_settings WHERE name = 'log_statement') AS log_statement,
        (SELECT setting FROM pg_settings WHERE name = 'log_connections') AS log_connections;
"""

_SUPERUSER_ROLES_WITHOUT_EXPIRATION_SQL = """
    SELECT rolname
    FROM pg_roles
    WHERE rolsuper
      AND rolvaliduntil IS NULL
    ORDER BY rolname;
"""

# rolconnlimit = -1 means unlimited concurrent connections for this role.
# Scoped to superuser login roles specifically (same base filter as
# _LOGIN_SUPERUSER_ROLES_SQL) rather than every role, to stay inside this
# bullet's actual theme (superuser blast radius) when folded into
# check_login_superuser_roles under the same slug.
_LOGIN_SUPERUSER_ROLES_WITHOUT_CONNECTION_LIMIT_SQL = """
    SELECT rolname
    FROM pg_roles
    WHERE rolcanlogin
      AND rolsuper
      AND rolconnlimit = -1
    ORDER BY rolname;
"""

# Direct complement of _RLS_ENABLED_WITHOUT_POLICIES_SQL: this finds the
# opposite gap -- RLS enabled *with* policies attached, but FORCE ROW LEVEL
# SECURITY never set, which silently exempts the table owner from every
# policy. A different, more subtle misconfiguration than "zero policies",
# same as how this file already documents the 08.02/07.03 distinction above.
_RLS_ENABLED_WITHOUT_FORCE_SQL = """
    SELECT
        n.nspname AS schema_name,
        c.relname AS table_name
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'r'
      AND c.relrowsecurity
      AND NOT c.relforcerowsecurity
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND EXISTS (
          SELECT 1 FROM pg_policies p
          WHERE p.schemaname = n.nspname AND p.tablename = c.relname
      )
    ORDER BY n.nspname, c.relname;
"""

# PUBLIC grants on any table with a PII-shaped column (reuses the same
# name heuristic as the undocumented-PII check above).
_PUBLIC_GRANTS_ON_PII_TABLES_SQL = """
    SELECT DISTINCT
        tp.table_schema AS schema_name,
        tp.table_name,
        tp.privilege_type
    FROM information_schema.table_privileges tp
    WHERE tp.grantee = 'PUBLIC'
      AND tp.table_schema NOT IN ('pg_catalog', 'information_schema')
      AND EXISTS (
          SELECT 1
          FROM information_schema.columns c
          WHERE c.table_schema = tp.table_schema
            AND c.table_name = tp.table_name
            AND c.column_name ~* %(pii_pattern)s
      )
    ORDER BY tp.table_schema, tp.table_name, tp.privilege_type;
"""

# pg_hba_file_rules is a genuine VIEW (despite the function-like name),
# restricted to superuser by default -- confirmed empirically (not
# documentation-assumed): granting pg_read_all_settings or even the broad
# pg_monitor role does NOT unlock it, only actual superuser membership does.
# A read-only audit role (this tool's expected real-world case, per db.py's
# own "read-only role covers ~90% of checks" framing) will almost always
# hit the privilege-gap path below, not the happy path -- this isn't an
# edge case to shrug off.
_IS_PG_HBA_FILE_RULES_READABLE_SQL = """
    SELECT has_table_privilege(current_user, 'pg_hba_file_rules', 'SELECT');
"""

_PG_HBA_RULES_SQL = """
    SELECT line_number, type, database, user_name, address, auth_method
    FROM pg_hba_file_rules
    ORDER BY line_number;
"""

# password_encryption is a cluster-wide setting, universally readable via
# pg_settings -- used here instead of inspecting pg_authid.rolpassword's
# hash-method prefix directly, which is normally restricted to superuser
# (or a role reading its own row only) and isn't a reliable per-role
# signal anyway once any role predates a password_encryption change.
_PASSWORD_ENCRYPTION_SETTING_SQL = """
    SELECT setting FROM pg_settings WHERE name = 'password_encryption';
"""


def fetch_login_superuser_roles(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_LOGIN_SUPERUSER_ROLES_SQL)
        return cur.fetchall()


def fetch_rls_enabled_without_policies(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_RLS_ENABLED_WITHOUT_POLICIES_SQL)
        return cur.fetchall()


def fetch_undocumented_pii_columns(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_UNDOCUMENTED_PII_COLUMNS_SQL, {"pii_pattern": PII_COLUMN_NAME_PATTERN})
        return cur.fetchall()


def fetch_ssl_setting(conn: psycopg.Connection) -> str:
    with conn.cursor() as cur:
        cur.execute(_SSL_SETTING_SQL)
        return cur.fetchone()[0]


def fetch_audit_trail_status(conn: psycopg.Connection) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_AUDIT_TRAIL_STATUS_SQL)
        return cur.fetchone()


def fetch_superuser_roles_without_expiration(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_SUPERUSER_ROLES_WITHOUT_EXPIRATION_SQL)
        return cur.fetchall()


def fetch_login_superuser_roles_without_connection_limit(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_LOGIN_SUPERUSER_ROLES_WITHOUT_CONNECTION_LIMIT_SQL)
        return cur.fetchall()


def fetch_rls_enabled_without_force(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_RLS_ENABLED_WITHOUT_FORCE_SQL)
        return cur.fetchall()


def fetch_public_grants_on_pii_tables(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_PUBLIC_GRANTS_ON_PII_TABLES_SQL, {"pii_pattern": PII_COLUMN_NAME_PATTERN})
        return cur.fetchall()


def is_pg_hba_file_rules_readable(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute(_IS_PG_HBA_FILE_RULES_READABLE_SQL)
        return cur.fetchone()[0]


def fetch_pg_hba_rules(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_PG_HBA_RULES_SQL)
        return cur.fetchall()


def fetch_password_encryption_setting(conn: psycopg.Connection) -> str:
    with conn.cursor() as cur:
        cur.execute(_PASSWORD_ENCRYPTION_SETTING_SQL)
        return cur.fetchone()[0]
