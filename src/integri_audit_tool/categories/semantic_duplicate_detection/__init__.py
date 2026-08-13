"""Semantic Duplicate Detection — new category from the SOP merge (2026-08-03).

Requires a per-engagement identity-fingerprint config (see
fingerprint_config.py) — what makes two rows "the same real-world entity"
is business knowledge no generic tool can guess, so this category is N/A
whenever `AuditConfig.duplicate_fingerprint_config` isn't supplied, rather
than attempting a default/guessed identity rule.

Two checks:
- exact-match-duplicates: identical normalized fingerprint. Ships as a
  normal, confirmed finding — the fingerprint rule itself was already
  human-approved when the config was authored.
- fuzzy-match-duplicates: pg_trgm similarity above the configured
  threshold. Each candidate requires human confirmation
  (`Check.interactive=True`, `Finding.requires_attestation=True`) before
  it's a real finding — see attestation.py/runner.py for how that
  pause/confirm flow works. Non-interactive runs ship candidates
  unconfirmed, clearly marked in the report rather than silently dropped
  or silently confirmed.

Current normalization vocabulary (`fingerprint_config.NORMALIZE_PRIMITIVES`)
is deliberately limited to simple string cleanup — lowercase, whitespace
stripping, digit/alphanumeric extraction. True semantic/unit normalization
(vendor "dictionaries" mapping product names, naming conventions, and
measurement units/formats onto a canonical form — see
integri-db-generator's UNS/DIN/JIS grade crosswalks for the shape this
will eventually take) is explicitly deferred (2026-08-05 direction) —
noted as a strong future candidate for an LLM-agent-based approach rather
than a purely algorithmic one, since normalizing "1/4 in" == "0.25in" ==
"6.35mm" isn't a fixed-regex problem.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks


def is_applicable(conn, config) -> bool:  # noqa: ANN001 - matches the shared applicability signature (see registry.py)
    return config.duplicate_fingerprint_config is not None


CATEGORY = CategoryModule(
    slug="semantic-duplicate-detection",
    name="Semantic Duplicate Detection",
    applicability=is_applicable,
    checks=[
        Check(
            slug="exact-match-duplicates",
            rubric_bullet=1,
            description="Do any rows share an identical normalized identity fingerprint?",
            fn=checks.check_exact_match_duplicates,
        ),
        Check(
            slug="fuzzy-match-duplicates",
            rubric_bullet=2,
            description="Do any rows look like the same real-world entity despite non-identical formatting?",
            fn=checks.check_fuzzy_match_duplicates,
            interactive=True,
        ),
    ],
)
