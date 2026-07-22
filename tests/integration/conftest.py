"""Fixtures for integration tests against a real, ephemeral Postgres instance.

Requires Docker. These tests are excluded from the default `pytest` run
(see `addopts` in pyproject.toml) and only execute via `pytest -m integration`.
"""

from __future__ import annotations

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container():
    # shared_preload_libraries is required for pg_stat_statements (category 4's
    # pg_stat_statements-based checks) — it can't be loaded via CREATE EXTENSION
    # alone, only at server start. Harmless for every other category's tests.
    container = PostgresContainer("postgres:16-alpine").with_command(
        "postgres -c shared_preload_libraries=pg_stat_statements -c pg_stat_statements.track=all"
    )
    with container as started:
        yield started


@pytest.fixture
def pg_conn(postgres_container):
    dsn = postgres_container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as conn:
        yield conn
