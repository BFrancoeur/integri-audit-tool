"""Semantic Duplicate Detection checks are tested against canned row data
(no live DB) — queries.py is what the integration suite validates against
real Postgres.
"""

import importlib

from integri_audit_tool.fingerprint_config import FingerprintConfig, FingerprintField
from integri_audit_tool.models import Severity

checks = importlib.import_module("integri_audit_tool.categories.semantic_duplicate_detection.checks")
package = importlib.import_module("integri_audit_tool.categories.semantic_duplicate_detection")


def _fp_config(**overrides):
    defaults = {
        "schema": "public",
        "table": "parts",
        "id_column": "id",
        "fields": (FingerprintField(column="material_grade", normalize=("lowercase", "strip_whitespace")),),
    }
    defaults.update(overrides)
    return FingerprintConfig(**defaults)


def _audit_config(mocker, duplicate_fingerprint_config="/tmp/fp.toml"):
    return mocker.Mock(duplicate_fingerprint_config=duplicate_fingerprint_config)


def test_is_applicable_false_without_config(mocker):
    config = mocker.Mock(duplicate_fingerprint_config=None)
    assert package.is_applicable(conn=object(), config=config) is False


def test_is_applicable_true_with_config(mocker):
    config = mocker.Mock(duplicate_fingerprint_config="/tmp/fp.toml")
    assert package.is_applicable(conn=object(), config=config) is True


def test_check_exact_match_duplicates_flags_row(mocker):
    mocker.patch.object(checks, "load_fingerprint_config", return_value=_fp_config())
    mocker.patch.object(
        checks.queries,
        "fetch_exact_match_duplicates",
        return_value=[{"fingerprint": "1045|", "matching_ids": [1, 2], "match_count": 2}],
    )

    findings = checks.check_exact_match_duplicates(conn=object(), config=_audit_config(mocker))

    assert len(findings) == 1
    assert findings[0].check_slug == "exact-match-duplicates"
    assert findings[0].severity == Severity.MEDIUM
    assert findings[0].requires_attestation is False
    assert "2 rows" in findings[0].title


def test_check_exact_match_duplicates_empty_when_none(mocker):
    mocker.patch.object(checks, "load_fingerprint_config", return_value=_fp_config())
    mocker.patch.object(checks.queries, "fetch_exact_match_duplicates", return_value=[])

    assert checks.check_exact_match_duplicates(conn=object(), config=_audit_config(mocker)) == []


def test_check_fuzzy_match_duplicates_informational_when_pg_trgm_unavailable(mocker):
    mocker.patch.object(checks.queries, "is_pg_trgm_available", return_value=False)

    findings = checks.check_fuzzy_match_duplicates(conn=object(), config=_audit_config(mocker))

    assert len(findings) == 1
    assert findings[0].check_slug == "fuzzy-match-duplicates"
    assert findings[0].severity == Severity.INFORMATIONAL
    assert findings[0].requires_attestation is False


def test_check_fuzzy_match_duplicates_flags_candidate_requiring_attestation(mocker):
    mocker.patch.object(checks.queries, "is_pg_trgm_available", return_value=True)
    mocker.patch.object(checks, "load_fingerprint_config", return_value=_fp_config())
    mocker.patch.object(
        checks.queries,
        "fetch_fuzzy_match_candidates",
        return_value=[{"fingerprint_a": "1045steel", "fingerprint_b": "1045steal", "sim": 0.85}],
    )

    findings = checks.check_fuzzy_match_duplicates(conn=object(), config=_audit_config(mocker))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_slug == "fuzzy-match-duplicates"
    assert finding.severity == Severity.MEDIUM
    assert finding.requires_attestation is True
    assert "85%" in finding.observation


def test_check_fuzzy_match_duplicates_empty_when_no_candidates(mocker):
    mocker.patch.object(checks.queries, "is_pg_trgm_available", return_value=True)
    mocker.patch.object(checks, "load_fingerprint_config", return_value=_fp_config())
    mocker.patch.object(checks.queries, "fetch_fuzzy_match_candidates", return_value=[])

    assert checks.check_fuzzy_match_duplicates(conn=object(), config=_audit_config(mocker)) == []


def test_fuzzy_match_check_is_registered_interactive():
    fuzzy_check = next(c for c in package.CATEGORY.checks if c.slug == "fuzzy-match-duplicates")
    assert fuzzy_check.interactive is True


def test_exact_match_check_is_not_registered_interactive():
    exact_check = next(c for c in package.CATEGORY.checks if c.slug == "exact-match-duplicates")
    assert exact_check.interactive is False
