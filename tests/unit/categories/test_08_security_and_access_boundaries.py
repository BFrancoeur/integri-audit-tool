"""Category 8 checks are tested against canned row data (no live DB) —
queries.py is what the integration suite validates against real Postgres.
"""

import importlib

from integri_audit_tool.models import Severity

checks = importlib.import_module("integri_audit_tool.categories.08_security_and_access_boundaries.checks")


def test_check_login_superuser_roles_flags_row(mocker):
    mocker.patch.object(checks.queries, "fetch_login_superuser_roles", return_value=[{"rolname": "postgres"}])

    findings = checks.check_login_superuser_roles(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "login-superuser-roles"
    assert findings[0].severity == Severity.MEDIUM
    assert "postgres" in findings[0].title


def test_check_login_superuser_roles_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_login_superuser_roles", return_value=[])
    assert checks.check_login_superuser_roles(conn=object(), config=None) == []


def test_check_rls_enabled_without_policies_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_rls_enabled_without_policies",
        return_value=[{"schema_name": "public", "table_name": "invoices"}],
    )

    findings = checks.check_rls_enabled_without_policies(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "rls-enabled-without-policies"
    assert findings[0].severity == Severity.MEDIUM
    assert "invoices" in findings[0].title


def test_check_rls_enabled_without_policies_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_rls_enabled_without_policies", return_value=[])
    assert checks.check_rls_enabled_without_policies(conn=object(), config=None) == []


def test_check_undocumented_pii_and_ssl_flags_both(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_undocumented_pii_columns",
        return_value=[{"schema_name": "public", "table_name": "customers", "column_name": "email"}],
    )
    mocker.patch.object(checks.queries, "fetch_ssl_setting", return_value="off")

    findings = checks.check_undocumented_pii_and_ssl(conn=object(), config=None)

    assert len(findings) == 2
    pii_finding = next(f for f in findings if "email" in f.title)
    ssl_finding = next(f for f in findings if "SSL" in f.title)
    assert pii_finding.check_slug == "undocumented-pii-and-ssl"
    assert pii_finding.severity == Severity.LOW
    assert ssl_finding.check_slug == "undocumented-pii-and-ssl"
    assert ssl_finding.severity == Severity.MEDIUM


def test_check_undocumented_pii_and_ssl_empty_when_clean(mocker):
    mocker.patch.object(checks.queries, "fetch_undocumented_pii_columns", return_value=[])
    mocker.patch.object(checks.queries, "fetch_ssl_setting", return_value="on")
    assert checks.check_undocumented_pii_and_ssl(conn=object(), config=None) == []


def test_check_audit_trail_availability_flags_when_nothing_active(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_audit_trail_status",
        return_value={"pgaudit_enabled": False, "log_statement": "none", "log_connections": "off"},
    )

    findings = checks.check_audit_trail_availability(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "audit-trail-availability"
    assert findings[0].severity == Severity.MEDIUM


def test_check_audit_trail_availability_empty_when_pgaudit_enabled(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_audit_trail_status",
        return_value={"pgaudit_enabled": True, "log_statement": "none", "log_connections": "off"},
    )
    assert checks.check_audit_trail_availability(conn=object(), config=None) == []


def test_check_audit_trail_availability_empty_when_log_statement_set(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_audit_trail_status",
        return_value={"pgaudit_enabled": False, "log_statement": "mod", "log_connections": "off"},
    )
    assert checks.check_audit_trail_availability(conn=object(), config=None) == []


def test_check_superuser_roles_without_expiration_flags_row(mocker):
    mocker.patch.object(
        checks.queries, "fetch_superuser_roles_without_expiration", return_value=[{"rolname": "admin_temp"}]
    )

    findings = checks.check_superuser_roles_without_expiration(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "superuser-roles-without-expiration"
    assert findings[0].severity == Severity.MEDIUM
    assert "admin_temp" in findings[0].title


def test_check_superuser_roles_without_expiration_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_superuser_roles_without_expiration", return_value=[])
    assert checks.check_superuser_roles_without_expiration(conn=object(), config=None) == []
