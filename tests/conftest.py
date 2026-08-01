"""Shared test fixtures."""

from __future__ import annotations

import contextlib

import pytest

from integri_audit_tool.models import Finding, Severity


class _FakeConnection:
    """Stands in for a psycopg.Connection in tests whose check functions
    never actually touch conn — just needs .transaction() to exist as a
    no-op context manager, since runner.run_audit wraps every check call
    in one (see runner.py's per-check savepoint isolation)."""

    def transaction(self):
        return contextlib.nullcontext()


@pytest.fixture
def fake_conn():
    return _FakeConnection()


@pytest.fixture
def make_finding():
    def _make(**overrides) -> Finding:
        defaults = dict(
            check_slug="test-finding",
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
