"""Read-only Postgres connection handling.

This tool audits client databases and must never write to them — every
connection this factory hands out is placed into a read-only transaction
mode at the session level, so an accidental write in check code fails
loudly instead of landing on the client's database.

It also never runs unbounded against a client's database: connection
establishment and every server-side wait (a running query, a lock, an idle
transaction) are capped, so a malformed DSN or a query on a huge/locked
table fails with a clear, bounded error instead of hanging indefinitely.
A timed-out check surfaces through the normal per-check error path (see
runner.py's savepoint isolation) rather than needing special handling.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg

CONNECT_TIMEOUT_SECONDS = 10
"""Caps how long connection establishment itself can hang -- an
unreachable host or a malformed DSN fails within this window instead of
hanging indefinitely."""

STATEMENT_TIMEOUT_MS = 30_000
"""Caps how long any single audit query may run. Conservative default for
a read-only audit; override for engagements against unusually large
databases where a legitimate scan needs more room."""

LOCK_TIMEOUT_MS = 5_000
"""Caps how long a query waits to acquire a lock. An audit is read-only
and should never sit blocked behind another session's lock for long."""

IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS = 60_000
"""Caps how long a transaction may sit idle -- e.g. if the tool itself
hangs between queries -- before Postgres terminates the session, so a
stuck audit process can't hold locks/resources indefinitely."""


@contextmanager
def connect_read_only(
    dsn: str,
    *,
    connect_timeout_seconds: int = CONNECT_TIMEOUT_SECONDS,
    statement_timeout_ms: int = STATEMENT_TIMEOUT_MS,
    lock_timeout_ms: int = LOCK_TIMEOUT_MS,
    idle_in_transaction_session_timeout_ms: int = IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS,
) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(dsn, connect_timeout=connect_timeout_seconds)
    try:
        # Must be set before the first query -- it governs the transaction
        # psycopg is about to begin, not one already in progress.
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {statement_timeout_ms}")
            cur.execute(f"SET lock_timeout = {lock_timeout_ms}")
            cur.execute(f"SET idle_in_transaction_session_timeout = {idle_in_transaction_session_timeout_ms}")
        yield conn
    finally:
        conn.close()
