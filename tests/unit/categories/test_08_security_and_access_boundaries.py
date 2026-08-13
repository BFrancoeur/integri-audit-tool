"""Category 8 checks are tested against canned row data (no live DB) —
queries.py is what the integration suite validates against real Postgres.
"""

import importlib

from integri_audit_tool.models import Severity

checks = importlib.import_module("integri_audit_tool.categories.security_and_access_boundaries.checks")


def test_check_login_superuser_roles_flags_row(mocker):
    mocker.patch.object(checks.queries, "fetch_login_superuser_roles", return_value=[{"rolname": "postgres"}])
    mocker.patch.object(checks.queries, "fetch_login_superuser_roles_without_connection_limit", return_value=[])

    findings = checks.check_login_superuser_roles(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "login-superuser-roles"
    assert findings[0].severity == Severity.MEDIUM
    assert "postgres" in findings[0].title


def test_check_login_superuser_roles_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_login_superuser_roles", return_value=[])
    mocker.patch.object(checks.queries, "fetch_login_superuser_roles_without_connection_limit", return_value=[])
    assert checks.check_login_superuser_roles(conn=object(), config=None) == []


def test_check_login_superuser_roles_flags_unlimited_connections(mocker):
    mocker.patch.object(checks.queries, "fetch_login_superuser_roles", return_value=[])
    mocker.patch.object(
        checks.queries,
        "fetch_login_superuser_roles_without_connection_limit",
        return_value=[{"rolname": "service_account"}],
    )

    findings = checks.check_login_superuser_roles(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "login-superuser-roles"
    assert findings[0].severity == Severity.LOW
    assert "service_account" in findings[0].title


def test_check_rls_enabled_without_policies_flags_row(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_rls_enabled_without_policies",
        return_value=[{"schema_name": "public", "table_name": "invoices"}],
    )
    mocker.patch.object(checks.queries, "fetch_rls_enabled_without_force", return_value=[])

    findings = checks.check_rls_enabled_without_policies(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "rls-enabled-without-policies"
    assert findings[0].severity == Severity.MEDIUM
    assert "invoices" in findings[0].title


def test_check_rls_enabled_without_policies_empty_when_none(mocker):
    mocker.patch.object(checks.queries, "fetch_rls_enabled_without_policies", return_value=[])
    mocker.patch.object(checks.queries, "fetch_rls_enabled_without_force", return_value=[])
    assert checks.check_rls_enabled_without_policies(conn=object(), config=None) == []


def test_check_rls_enabled_without_policies_flags_missing_force(mocker):
    mocker.patch.object(checks.queries, "fetch_rls_enabled_without_policies", return_value=[])
    mocker.patch.object(
        checks.queries,
        "fetch_rls_enabled_without_force",
        return_value=[{"schema_name": "public", "table_name": "tenant_data"}],
    )

    findings = checks.check_rls_enabled_without_policies(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "rls-enabled-without-policies"
    assert findings[0].severity == Severity.LOW
    assert "tenant_data" in findings[0].title


def test_check_undocumented_pii_and_ssl_flags_all_three(mocker):
    mocker.patch.object(
        checks.queries,
        "fetch_undocumented_pii_columns",
        return_value=[{"schema_name": "public", "table_name": "customers", "column_name": "email"}],
    )
    mocker.patch.object(checks.queries, "fetch_ssl_setting", return_value="off")
    mocker.patch.object(
        checks.queries,
        "fetch_public_grants_on_pii_tables",
        return_value=[{"schema_name": "public", "table_name": "customers", "privilege_type": "SELECT"}],
    )

    findings = checks.check_undocumented_pii_and_ssl(conn=object(), config=None)

    assert len(findings) == 3
    pii_finding = next(f for f in findings if "Undocumented" in f.title)
    ssl_finding = next(f for f in findings if "SSL" in f.title)
    grant_finding = next(f for f in findings if "PUBLIC grant" in f.title)
    assert pii_finding.check_slug == "undocumented-pii-and-ssl"
    assert pii_finding.severity == Severity.LOW
    assert ssl_finding.check_slug == "undocumented-pii-and-ssl"
    assert ssl_finding.severity == Severity.MEDIUM
    assert grant_finding.check_slug == "undocumented-pii-and-ssl"
    assert grant_finding.severity == Severity.HIGH


def test_check_undocumented_pii_and_ssl_empty_when_clean(mocker):
    mocker.patch.object(checks.queries, "fetch_undocumented_pii_columns", return_value=[])
    mocker.patch.object(checks.queries, "fetch_ssl_setting", return_value="on")
    mocker.patch.object(checks.queries, "fetch_public_grants_on_pii_tables", return_value=[])
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


def test_check_authentication_method_strength_flags_trust_as_critical(mocker):
    mocker.patch.object(checks.queries, "is_pg_hba_file_rules_readable", return_value=True)
    mocker.patch.object(
        checks.queries,
        "fetch_pg_hba_rules",
        return_value=[
            {"line_number": 1, "type": "local", "database": "all", "user_name": "all", "address": None, "auth_method": "trust"}
        ],
    )
    mocker.patch.object(checks.queries, "fetch_password_encryption_setting", return_value="scram-sha-256")

    findings = checks.check_authentication_method_strength(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "authentication-method-strength"
    assert findings[0].severity == Severity.CRITICAL
    assert "trust" in findings[0].title


def test_check_authentication_method_strength_flags_password_as_high(mocker):
    mocker.patch.object(checks.queries, "is_pg_hba_file_rules_readable", return_value=True)
    mocker.patch.object(
        checks.queries,
        "fetch_pg_hba_rules",
        return_value=[
            {
                "line_number": 2,
                "type": "host",
                "database": "all",
                "user_name": "all",
                "address": "0.0.0.0/0",
                "auth_method": "password",
            }
        ],
    )
    mocker.patch.object(checks.queries, "fetch_password_encryption_setting", return_value="scram-sha-256")

    findings = checks.check_authentication_method_strength(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].severity == Severity.HIGH


def test_check_authentication_method_strength_ignores_scram_rules(mocker):
    mocker.patch.object(checks.queries, "is_pg_hba_file_rules_readable", return_value=True)
    mocker.patch.object(
        checks.queries,
        "fetch_pg_hba_rules",
        return_value=[
            {
                "line_number": 3,
                "type": "host",
                "database": "all",
                "user_name": "all",
                "address": "0.0.0.0/0",
                "auth_method": "scram-sha-256",
            }
        ],
    )
    mocker.patch.object(checks.queries, "fetch_password_encryption_setting", return_value="scram-sha-256")

    assert checks.check_authentication_method_strength(conn=object(), config=None) == []


def test_check_authentication_method_strength_degrades_gracefully_without_privilege(mocker):
    mocker.patch.object(checks.queries, "is_pg_hba_file_rules_readable", return_value=False)
    mock_fetch = mocker.patch.object(checks.queries, "fetch_pg_hba_rules")
    mocker.patch.object(checks.queries, "fetch_password_encryption_setting", return_value="scram-sha-256")

    findings = checks.check_authentication_method_strength(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].check_slug == "authentication-method-strength"
    assert findings[0].severity == Severity.INFORMATIONAL
    assert "insufficient privilege" in findings[0].title.lower()
    mock_fetch.assert_not_called()


def test_check_authentication_method_strength_flags_weak_password_encryption(mocker):
    mocker.patch.object(checks.queries, "is_pg_hba_file_rules_readable", return_value=True)
    mocker.patch.object(checks.queries, "fetch_pg_hba_rules", return_value=[])
    mocker.patch.object(checks.queries, "fetch_password_encryption_setting", return_value="md5")

    findings = checks.check_authentication_method_strength(conn=object(), config=None)

    assert len(findings) == 1
    assert findings[0].severity == Severity.MEDIUM
    assert "md5" in findings[0].title


def test_check_authentication_method_strength_empty_when_everything_strong(mocker):
    mocker.patch.object(checks.queries, "is_pg_hba_file_rules_readable", return_value=True)
    mocker.patch.object(checks.queries, "fetch_pg_hba_rules", return_value=[])
    mocker.patch.object(checks.queries, "fetch_password_encryption_setting", return_value="scram-sha-256")

    assert checks.check_authentication_method_strength(conn=object(), config=None) == []
