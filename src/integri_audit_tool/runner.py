"""Orchestrates a full audit run: discover categories, run checks, assemble the report."""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg

from integri_audit_tool import registry
from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import AuditReport, CategoryResult, Finding, Severity


def run_audit(conn: psycopg.Connection, config: AuditConfig, target_label: str) -> AuditReport:
    results: list[CategoryResult] = []

    for category in registry.discover_categories():
        if config.category_filter is not None and category.number not in config.category_filter:
            continue

        if category.applicability is not None and not category.applicability(conn):
            results.append(
                CategoryResult(
                    category_number=category.number,
                    category_name=category.name,
                    status="not_applicable",
                    na_reason="Category does not apply to this database (applicability check returned False).",
                )
            )
            continue

        findings: list[Finding] = []
        for check in category.checks:
            try:
                findings.extend(check.fn(conn, config))
            except Exception as exc:  # noqa: BLE001 - one bad check must not abort the run
                findings.append(
                    Finding(
                        category_number=category.number,
                        category_name=category.name,
                        check_id=check.id,
                        title=f"Check {check.id} could not be run",
                        severity=Severity.INFORMATIONAL,
                        observation=f"{check.description}\n\nThe check raised an error and was skipped: {exc}",
                    )
                )

        results.append(
            CategoryResult(
                category_number=category.number,
                category_name=category.name,
                status="completed",
                findings=findings,
            )
        )

    return AuditReport(
        target_label=target_label,
        generated_at=datetime.now(timezone.utc),
        category_results=results,
    )
