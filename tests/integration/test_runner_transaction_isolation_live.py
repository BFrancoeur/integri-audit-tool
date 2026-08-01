"""Regression coverage for the per-check savepoint isolation in runner.py.

Requires a real Postgres instance: an aborted-transaction state (what a real
SQL error actually produces) can't be meaningfully faked with a mock cursor,
so this has to run against the genuine `postgres_container`/`db.connect_read_only`
path rather than tests/unit/test_runner.py's fake `conn=object()`. Marked
`integration`; run explicitly with `pytest -m integration` (requires Docker).
"""

from __future__ import annotations

import pytest

from integri_audit_tool import db, runner
from integri_audit_tool.config import AuditConfig
from integri_audit_tool.registry import Check, CategoryModule

pytestmark = pytest.mark.integration


def _run_invalid_sql(conn, config):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM this_table_does_not_exist_at_all_xyz")
    return []


def _run_valid_sql(conn, config):
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
    return []


def test_a_failing_checks_sql_error_does_not_poison_later_checks(postgres_container, monkeypatch):
    dsn = postgres_container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    category = CategoryModule(
        slug="fake-category",
        number=99,
        name="Fake Category",
        checks=[
            Check(slug="fails", rubric_bullet=1, description="fails", fn=_run_invalid_sql),
            Check(slug="succeeds", rubric_bullet=2, description="succeeds", fn=_run_valid_sql),
        ],
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [category])

    with db.connect_read_only(dsn) as conn:
        report = runner.run_audit(conn=conn, config=AuditConfig(dsn=dsn), target_label="test-db")

    check_results = {cr.check_slug: cr for cr in report.category_results[0].check_results}
    assert check_results["fails"].status == "error"
    # Without a per-check savepoint, this would also come back "error" with
    # "current transaction is aborted" -- not because its own SQL is invalid,
    # but because the previous check's failure poisoned the shared transaction.
    assert check_results["succeeds"].status == "passed"
