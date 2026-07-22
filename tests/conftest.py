"""Shared test fixtures."""

from __future__ import annotations

import pytest

from integri_audit_tool.models import Finding, Severity


@pytest.fixture
def make_finding():
    def _make(**overrides) -> Finding:
        defaults = dict(
            category_number=1,
            category_name="Test Category",
            check_id="01.01",
            title="Test finding",
            severity=Severity.LOW,
            observation="Observed something.",
        )
        defaults.update(overrides)
        return Finding(**defaults)

    return _make
