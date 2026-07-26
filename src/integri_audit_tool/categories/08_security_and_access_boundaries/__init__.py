"""Rubric category 8: Security & Access Boundaries.

5 of the rubric's 6 checklist bullets are implemented, all from read-only
catalog access (pg_roles, pg_policies, pg_settings, pg_extension) — no row
sampling, no pg_stat_statements dependency:
- 08.01 login roles with SUPERUSER (least-privilege violation candidates)
- 08.02 RLS enabled with zero policies attached (a different failure mode
  than category 7's 07.03, which covers tenant columns with RLS never
  enabled at all — see queries.py for why these aren't the same check)
- 08.04 PII-heuristic columns with no documentation, and server SSL not
  enabled (both sub-checks live under one bullet, matching the rubric's own
  "flagged, and encrypted... appropriately" wording)
- 08.05 no audit trail mechanism (neither pgaudit nor log_statement active)
- 08.06 superuser roles with no VALID UNTIL expiration

08.03 (secrets stored outside version control and application code) is
declared via `out_of_scope`: nothing about where an application's config or
.env files live is visible from inside the database it connects to.

No `applicability` — every database has roles, so this category is never N/A.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    slug="security-and-access-boundaries",
    name="Security & Access Boundaries",
    checks=[
        Check(
            slug="login-superuser-roles",
            rubric_bullet=1,
            description="Are database roles scoped by least privilege (no shared superuser login)?",
            fn=checks.check_login_superuser_roles,
        ),
        Check(
            slug="rls-enabled-without-policies",
            rubric_bullet=2,
            description="Is row-level security in use where multi-tenant isolation is required?",
            fn=checks.check_rls_enabled_without_policies,
        ),
        Check(
            slug="undocumented-pii-and-ssl",
            rubric_bullet=4,
            description="Is sensitive data flagged, and encrypted in transit appropriately?",
            fn=checks.check_undocumented_pii_and_ssl,
        ),
        Check(
            slug="audit-trail-availability",
            rubric_bullet=5,
            description="Are audit logs available for who changed what?",
            fn=checks.check_audit_trail_availability,
        ),
        Check(
            slug="superuser-roles-without-expiration",
            rubric_bullet=6,
            description="Are elevated/temporary access grants time-boxed with automatic expiration?",
            fn=checks.check_superuser_roles_without_expiration,
        ),
    ],
    out_of_scope=[
        "Category 8, bullet 08.03 (are secrets like connection strings and credentials stored outside "
        "version control and application code?) — nothing about where an application's configuration or "
        ".env files live is visible from inside the database it connects to.",
    ],
)
