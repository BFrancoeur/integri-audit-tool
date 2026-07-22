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

queries = importlib.import_module("integri_audit_tool.categories.08_security_and_access_boundaries.queries")

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
