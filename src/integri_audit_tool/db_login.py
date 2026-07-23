"""Interactively collects Postgres-level credentials, builds a DSN, and
connects — kept as its own module, separate from ssh_tunnel.py, since the
two are genuinely independent concerns: this module doesn't know or care
whether the host it's connecting to is a client's database reached
directly, or 127.0.0.1:<forwarded-port> reached through an SSH tunnel.

The actual read-only connection guarantee is entirely owned by db.py's
connect_read_only, unchanged and reused here, not duplicated — this module
is only responsible for gathering/assembling connection parameters.
"""

from __future__ import annotations

import getpass
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import quote

import psycopg
import typer

from integri_audit_tool.db import connect_read_only


@dataclass(frozen=True)
class DbLoginConfig:
    host: str
    port: int
    username: str
    password: str
    database: str


def prompt_for_db_login(default_host: str, default_port: int) -> DbLoginConfig:
    """Prompts for Postgres-level credentials. default_host/default_port let
    a caller pre-fill the values that come from an SSH tunnel's local
    forwarded port (see ssh_tunnel.py) — pass the real host/port directly
    when connecting without a tunnel.
    """
    host_raw = input(f"Database host [{default_host}]: ").strip()
    host = host_raw or default_host

    port_raw = input(f"Database port [{default_port}]: ").strip()
    port = int(port_raw) if port_raw else default_port

    username = input("Database username: ").strip()
    if not username:
        typer.echo("Database username cannot be empty.", err=True)
        raise typer.Exit(code=1)

    password = getpass.getpass("Database password: ")

    database = input("Database name: ").strip()
    if not database:
        typer.echo("Database name cannot be empty.", err=True)
        raise typer.Exit(code=1)

    return DbLoginConfig(host=host, port=port, username=username, password=password, database=database)


def build_dsn(config: DbLoginConfig) -> str:
    # safe="" — quote()'s default leaves "/" unescaped (it assumes a URL
    # path), which would be wrong here: a literal "/" in a password or
    # database name must be percent-encoded too, or it gets misread as a
    # DSN component separator.
    return (
        f"postgresql://{quote(config.username, safe='')}:{quote(config.password, safe='')}"
        f"@{config.host}:{config.port}/{quote(config.database, safe='')}"
    )


@contextmanager
def connect(config: DbLoginConfig) -> Iterator[psycopg.Connection]:
    with connect_read_only(build_dsn(config)) as conn:
        yield conn
