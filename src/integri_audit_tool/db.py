"""Read-only Postgres connection handling.

This tool audits client databases and must never write to them — every
connection this factory hands out is placed into a read-only transaction
mode at the session level, so an accidental write in check code fails
loudly instead of landing on the client's database.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg


@contextmanager
def connect_read_only(dsn: str) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(dsn)
    try:
        conn.read_only = True
        yield conn
    finally:
        conn.close()
