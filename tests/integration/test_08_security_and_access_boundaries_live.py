"""Integration coverage for category 8's raw SQL against a real Postgres instance.

Unlike tests/unit/categories/test_08_security_and_access_boundaries.py
(canned rows), these validate that the SQL in queries.py is actually correct.
Marked `integration`; run explicitly with `pytest -m integration` (requires
Docker).

Table/role names are prefixed `c8_` to avoid colliding with other categories'
test objects in the shared, session-scoped test container. Roles are
cluster-wide (not per-database) but uniquely named, so they don't collide
with anything else in the shared container.
"""

import importlib

import pytest

queries = importlib.import_module("integri_audit_tool.categories.security_and_access_boundaries.queries")

pytestmark = pytest.mark.integration


def test_fetch_login_superuser_roles_includes_bootstrap_user(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("SELECT current_user")
        current_user = cur.fetchone()[0]

    rows = queries.fetch_login_superuser_roles(pg_conn)

    assert any(r["rolname"] == current_user for r in rows)


def test_fetch_rls_enabled_without_policies_distinguishes_policy_coverage(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c8_invoices (id serial PRIMARY KEY)")
        cur.execute("ALTER TABLE c8_invoices ENABLE ROW LEVEL SECURITY")
        cur.execute("CREATE TABLE c8_secured_invoices (id serial PRIMARY KEY)")
        cur.execute("ALTER TABLE c8_secured_invoices ENABLE ROW LEVEL SECURITY")
        cur.execute("CREATE POLICY c8_secured_invoices_policy ON c8_secured_invoices USING (true)")

    rows = queries.fetch_rls_enabled_without_policies(pg_conn)

    assert any(r["table_name"] == "c8_invoices" for r in rows)
    assert not any(r["table_name"] == "c8_secured_invoices" for r in rows)


def test_fetch_undocumented_pii_columns_distinguishes_documented_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c8_customers (id serial PRIMARY KEY, email text, ssn text)")
        cur.execute("COMMENT ON COLUMN c8_customers.ssn IS 'Encrypted SSN, PII - restricted access'")

    rows = queries.fetch_undocumented_pii_columns(pg_conn)

    assert any(r["table_name"] == "c8_customers" and r["column_name"] == "email" for r in rows)
    assert not any(r["table_name"] == "c8_customers" and r["column_name"] == "ssn" for r in rows)


def test_fetch_ssl_setting_returns_on_or_off(pg_conn):
    setting = queries.fetch_ssl_setting(pg_conn)
    assert setting in ("on", "off")


def test_fetch_audit_trail_status_returns_expected_shape(pg_conn):
    status = queries.fetch_audit_trail_status(pg_conn)

    assert isinstance(status["pgaudit_enabled"], bool)
    assert isinstance(status["log_statement"], str)
    assert isinstance(status["log_connections"], str)


def test_fetch_superuser_roles_without_expiration_distinguishes_expiring_role(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("SELECT current_user")
        current_user = cur.fetchone()[0]
        cur.execute("CREATE ROLE c8_temp_admin WITH LOGIN SUPERUSER VALID UNTIL '2099-01-01'")

    rows = queries.fetch_superuser_roles_without_expiration(pg_conn)

    assert any(r["rolname"] == current_user for r in rows)
    assert not any(r["rolname"] == "c8_temp_admin" for r in rows)


def test_fetch_login_superuser_roles_without_connection_limit_distinguishes_limited_role(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE ROLE c8_unlimited_admin WITH LOGIN SUPERUSER CONNECTION LIMIT -1")
        cur.execute("CREATE ROLE c8_limited_admin WITH LOGIN SUPERUSER CONNECTION LIMIT 5")

    rows = queries.fetch_login_superuser_roles_without_connection_limit(pg_conn)

    assert any(r["rolname"] == "c8_unlimited_admin" for r in rows)
    assert not any(r["rolname"] == "c8_limited_admin" for r in rows)


def test_fetch_rls_enabled_without_force_distinguishes_forced_table(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c8_no_force (id serial PRIMARY KEY)")
        cur.execute("ALTER TABLE c8_no_force ENABLE ROW LEVEL SECURITY")
        cur.execute("CREATE POLICY c8_no_force_policy ON c8_no_force USING (true)")
        cur.execute("CREATE TABLE c8_forced (id serial PRIMARY KEY)")
        cur.execute("ALTER TABLE c8_forced ENABLE ROW LEVEL SECURITY")
        cur.execute("ALTER TABLE c8_forced FORCE ROW LEVEL SECURITY")
        cur.execute("CREATE POLICY c8_forced_policy ON c8_forced USING (true)")

    rows = queries.fetch_rls_enabled_without_force(pg_conn)

    assert any(r["table_name"] == "c8_no_force" for r in rows)
    assert not any(r["table_name"] == "c8_forced" for r in rows)


def test_fetch_public_grants_on_pii_tables_distinguishes_scoped_grant(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("CREATE TABLE c8_public_grant_customers (id serial PRIMARY KEY, email text)")
        cur.execute("GRANT SELECT ON c8_public_grant_customers TO PUBLIC")
        cur.execute("CREATE TABLE c8_scoped_grant_customers (id serial PRIMARY KEY, email text)")

    rows = queries.fetch_public_grants_on_pii_tables(pg_conn)

    assert any(r["table_name"] == "c8_public_grant_customers" and r["privilege_type"] == "SELECT" for r in rows)
    assert not any(r["table_name"] == "c8_scoped_grant_customers" for r in rows)


def test_is_pg_hba_file_rules_readable_true_for_superuser_connection(pg_conn):
    # testcontainers connects as a superuser by default, so the happy path
    # is what's exercised live here; the privilege-gap path (confirmed
    # empirically during design against a real unprivileged role) is
    # covered by mocking in the unit tests -- standing up a second,
    # differently-privileged connection isn't worth the complexity for
    # what's fundamentally a SQL-correctness test.
    assert queries.is_pg_hba_file_rules_readable(pg_conn) is True


def test_fetch_pg_hba_rules_returns_well_formed_rows(pg_conn):
    rows = queries.fetch_pg_hba_rules(pg_conn)

    assert len(rows) > 0
    for row in rows:
        assert row["line_number"] > 0
        assert row["auth_method"]


def test_fetch_password_encryption_setting_returns_a_known_value(pg_conn):
    setting = queries.fetch_password_encryption_setting(pg_conn)
    assert setting in ("scram-sha-256", "md5")
