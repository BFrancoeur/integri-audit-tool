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
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
def pg_conn(postgres_container):
    dsn = postgres_container.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as conn:
        yield conn
