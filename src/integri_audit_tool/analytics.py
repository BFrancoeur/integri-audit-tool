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

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name TEXT,
    target_label TEXT NOT NULL,
    database_name TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    category_filter TEXT,
    check_filter TEXT
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES audit_runs(id),
    category_number INTEGER NOT NULL,
    category_name TEXT NOT NULL,
    check_id TEXT NOT NULL,
    title TEXT NOT NULL,
    severity TEXT NOT NULL,
    observation TEXT NOT NULL,
    evidence TEXT,
    business_impact TEXT NOT NULL DEFAULT '',
    recommended_direction TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_findings_run_id ON findings(run_id);
CREATE INDEX IF NOT EXISTS idx_findings_check_id ON findings(check_id);
CREATE INDEX IF NOT EXISTS idx_audit_runs_is_synthetic ON audit_runs(is_synthetic);
"""


def _database_name_from_label(target_label: str) -> str:
    """target_label is always "host:port/dbname" — the part after the last
    "/" is the database name. Duplicated from report/markdown.py's
    identical helper rather than imported: this module intentionally has
    no dependency on the report package, since persistence and rendering
    are separate concerns that happen to need the same one-line parse."""
    return target_label.rsplit("/", 1)[-1] if "/" in target_label else target_label


class AuditDatabaseWriter:
    """Writes one audit_runs row per run and one findings row per Finding,
    lazily — the run row is created on the first category with any
    findings, or in audit_completed as a fallback so a fully clean audit
    (zero findings anywhere) still leaves a record rather than vanishing
    silently."""

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
            cursor = conn.execute(
                "INSERT INTO audit_runs "
                "(client_name, target_label, database_name, generated_at, is_synthetic, "
                "category_filter, check_filter) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    self._client_name,
                    self._target_label,
                    _database_name_from_label(self._target_label),
                    datetime.now(timezone.utc).isoformat(),
                    int(self._is_synthetic),
                    self._category_filter,
                    self._check_filter,
                ),
            )
            conn.commit()
            self._run_id = cursor.lastrowid
        return self._run_id

    def category_ready(self, category, checks_to_run) -> None:  # noqa: ANN001 - matches Protocol structurally
        pass

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
                "(run_id, category_number, category_name, check_id, title, severity, "
                "observation, evidence, business_impact, recommended_direction) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        f.category_number,
                        f.category_name,
                        f.check_id,
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
        self._ensure_run_row()
