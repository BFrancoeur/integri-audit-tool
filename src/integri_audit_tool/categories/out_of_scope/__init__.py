"""Out of Scope — not a category this tool ever assesses.

Has no checks and never will (`out_of_scope_only=True` tells runner.py to
always include it regardless of --category/--check filtering, and tells
report/markdown.py to render its `out_of_scope` list as its body content
instead of "No findings." or "no checks implemented yet"). It exists to
consolidate, in one place, every domain this audit deliberately does not
cover — distinct from a specific rubric bullet within an otherwise in-scope
category (e.g. category 4's UI-only facet logic), which stays declared on
that category's own `out_of_scope` list and is collected here too, the same
way every category's out_of_scope bullets always have been.
"""

from integri_audit_tool.registry import CategoryModule

_COMPLIANCE_AND_DATA_PRIVACY_NOTE = (
    "Compliance & Data Privacy — data-subject rights (access, rectification, "
    "deletion/\"right to be forgotten,\" portability), documented legal basis / "
    "consent tracking, retention and minimization policy enforcement, cross-border "
    "transfer safeguards, breach-notification readiness, SOC2 Trust Services "
    "Criteria mapping, and vendor DPAs are almost entirely manual-confirmation / "
    "human-verified. A read-only database connection can surface supporting "
    "signals (PII column detection, encryption-in-transit signals, row-level-"
    "security presence — see Security & Access Boundaries) but cannot confirm "
    "legal basis, consent records, DPAs, or breach-notification readiness on its "
    "own. This is a legal/compliance review, not a database audit finding."
)

_NETWORK_AND_INFRASTRUCTURE_SECURITY_NOTE = (
    "Network & Infrastructure Security — network-level security (port scanning, "
    "firewall/security-group review, VPN/bastion-host setup, exposed-service "
    "enumeration), penetration testing or vulnerability scanning of any kind, "
    "OS/host-level hardening beyond what's visible through the database connection "
    "itself, and application-layer security (authentication flows, session "
    "management, API security) outside what's directly visible from within the "
    "database. This is a different discipline with a different authorization and "
    "liability profile than reading a database with credentials already granted "
    "for that purpose — testing any of the above without separate, explicit "
    "written authorization risks looking like unauthorized security testing "
    "regardless of intent."
)

CATEGORY = CategoryModule(
    slug="out-of-scope",
    name="Out of Scope",
    checks=[],
    out_of_scope_only=True,
    out_of_scope=[
        _COMPLIANCE_AND_DATA_PRIVACY_NOTE,
        _NETWORK_AND_INFRASTRUCTURE_SECURITY_NOTE,
    ],
)
