"""Regression coverage for db.py's session-level timeouts against a real
Postgres instance.

Requires a real Postgres instance -- a timeout actually elapsing and
Postgres cancelling the query in response can't be meaningfully faked with
a mock cursor. Marked `integration`; run explicitly with
`pytest -m integration` (requires Docker).
"""

from __future__ import annotations

import psycopg
import pytest

from integri_audit_tool import db

pytestmark = pytest.mark.integration


def test_statement_timeout_cancels_a_long_running_query(postgres_container):
    dsn = postgres_container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")

    with db.connect_read_only(dsn, statement_timeout_ms=200) as conn:
        with pytest.raises(psycopg.errors.QueryCanceled):
            with conn.cursor() as cur:
                cur.execute("SELECT pg_sleep(2)")


def test_default_timeouts_allow_a_normal_query_to_complete(postgres_container):
    dsn = postgres_container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")

    with db.connect_read_only(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
