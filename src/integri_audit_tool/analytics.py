"""Persists audit results to a local SQLite database for cross-run
analysis — trend-spotting across an accumulated client base (or, just as
usefully, across a deliberately-generated corpus of synthetic training
runs) that a single Markdown/PDF report per engagement can't give you on
its own.

Implements the AuditReporter Protocol structurally (category_completed
does the actual persisting; the rest are no-ops), mirroring cli.py's
_IncrementalReportWriter's pattern. Kept as its own module rather than
folded into cli.py since the schema/persistence logic is substantial
enough to deserve independent testing — consistent with
ssh_tunnel.py/db_login.py/pdf_export.py all being separate concerns from
CLI orchestration.

Never mixed with the client-facing deliverable: this is purely an
internal accumulator, and analytics.db is gitignored the same as
reports/ and logs/ — it will contain client-identifying details and
must never be committed.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from integri_audit_tool.models import AuditReport, CategoryResult
    from integri_audit_tool.registry import Check, CategoryModule

DEFAULT_DB_PATH = Path("analytics.db")

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"

_STATUS_COLUMN = "status"
_COMPLETED_AT_COLUMN = "completed_at"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS audit_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name TEXT,
    target_label TEXT NOT NULL,
    database_name TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    category_filter TEXT,
    check_filter TEXT,
    {_STATUS_COLUMN} TEXT NOT NULL DEFAULT '{STATUS_RUNNING}',
    {_COMPLETED_AT_COLUMN} TEXT
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES audit_runs(id),
    category_number INTEGER NOT NULL,
    category_name TEXT NOT NULL,
    check_id TEXT NOT NULL,
    check_slug TEXT NOT NULL,
    title TEXT NOT NULL,
    severity TEXT NOT NULL,
    observation TEXT NOT NULL,
    evidence TEXT,
    business_impact TEXT NOT NULL DEFAULT '',
    recommended_direction TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_findings_run_id ON findings(run_id);
CREATE INDEX IF NOT EXISTS idx_findings_check_id ON findings(check_id);
CREATE INDEX IF NOT EXISTS idx_findings_check_slug ON findings(check_slug);
CREATE INDEX IF NOT EXISTS idx_audit_runs_is_synthetic ON audit_runs(is_synthetic);
"""


def _database_name_from_label(target_label: str) -> str:
    """target_label is always "host:port/dbname" — the part after the last
    "/" is the database name. Duplicated from report/markdown.py's
    identical helper rather than imported: this module intentionally has
    no dependency on the report package, since persistence and rendering
    are separate concerns that happen to need the same one-line parse."""
    return target_label.rsplit("/", 1)[-1] if "/" in target_label else target_label


def _ensure_run_lifecycle_columns(conn: sqlite3.Connection) -> None:
    """audit_runs may already exist without status/completed_at, from an
    analytics.db created by a version of this tool that predates them --
    CREATE TABLE IF NOT EXISTS alone never adds columns to an existing
    table, so migrate it explicitly. Safe to call every time; a no-op once
    both columns are present."""
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_runs)")}
    if _STATUS_COLUMN not in existing_columns:
        conn.execute(f"ALTER TABLE audit_runs ADD COLUMN {_STATUS_COLUMN} TEXT NOT NULL DEFAULT '{STATUS_RUNNING}'")
    if _COMPLETED_AT_COLUMN not in existing_columns:
        conn.execute(f"ALTER TABLE audit_runs ADD COLUMN {_COMPLETED_AT_COLUMN} TEXT")


class AuditDatabaseWriter:
    """Writes one audit_runs row per run (created as soon as the first
    category is ready to run, status='running') and one findings row per
    Finding. audit_completed marks the run 'completed' -- a process that
    crashes partway through leaves its row stuck at 'running' rather than
    looking indistinguishable from a real completed run."""

    def __init__(
        self,
        target_label: str,
        client_name: str | None = None,
        is_synthetic: bool = False,
        category_filter: str | None = None,
        check_filter: str | None = None,
        db_path: Path | str = DEFAULT_DB_PATH,
    ) -> None:
        self._db_path = Path(db_path)
        self._target_label = target_label
        self._client_name = client_name
        self._is_synthetic = is_synthetic
        self._category_filter = category_filter
        self._check_filter = check_filter
        self._run_id: int | None = None

    def _ensure_run_row(self) -> int:
        if self._run_id is not None:
            return self._run_id
        with closing(sqlite3.connect(self._db_path)) as conn:
            conn.executescript(_SCHEMA)
            _ensure_run_lifecycle_columns(conn)
            cursor = conn.execute(
                "INSERT INTO audit_runs "
                "(client_name, target_label, database_name, generated_at, is_synthetic, "
                f"category_filter, check_filter, {_STATUS_COLUMN}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._client_name,
                    self._target_label,
                    _database_name_from_label(self._target_label),
                    datetime.now(timezone.utc).isoformat(),
                    int(self._is_synthetic),
                    self._category_filter,
                    self._check_filter,
                    STATUS_RUNNING,
                ),
            )
            conn.commit()
            self._run_id = cursor.lastrowid
        return self._run_id

    def category_ready(self, category, checks_to_run) -> None:  # noqa: ANN001 - matches Protocol structurally
        # As early as the run's lifecycle gets — before this category's (or
        # any category's) checks execute — so a crash anywhere after this
        # point leaves a row correctly stuck at status='running' rather
        # than no row at all.
        self._ensure_run_row()

    def category_not_applicable(self, category, reason) -> None:  # noqa: ANN001
        pass

    def check_started(self, category, check) -> None:  # noqa: ANN001
        pass

    def check_succeeded(self, category, check, findings) -> None:  # noqa: ANN001
        pass

    def check_failed(self, category, check, error) -> None:  # noqa: ANN001
        pass

    def category_completed(self, category: "CategoryModule", result: "CategoryResult") -> None:
        if not result.findings:
            return
        run_id = self._ensure_run_row()
        with closing(sqlite3.connect(self._db_path)) as conn:
            conn.executemany(
                "INSERT INTO findings "
                "(run_id, category_number, category_name, check_id, check_slug, title, severity, "
                "observation, evidence, business_impact, recommended_direction) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        f.category_number,
                        f.category_name,
                        f.check_id,
                        f.check_slug,
                        f.title,
                        f.severity.value,
                        f.observation,
                        f.evidence,
                        f.business_impact,
                        f.recommended_direction,
                    )
                    for f in result.findings
                ],
            )
            conn.commit()

    def audit_completed(self, report: "AuditReport") -> None:
        run_id = self._ensure_run_row()
        with closing(sqlite3.connect(self._db_path)) as conn:
            conn.execute(
                f"UPDATE audit_runs SET {_STATUS_COLUMN} = ?, {_COMPLETED_AT_COLUMN} = ? WHERE id = ?",
                (STATUS_COMPLETED, datetime.now(timezone.utc).isoformat(), run_id),
            )
            conn.commit()
