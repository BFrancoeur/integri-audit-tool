"""Orchestrates a full audit run: discover categories, run checks, assemble the report."""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg

from integri_audit_tool import registry
from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import CATEGORY_12_OUT_OF_SCOPE_NOTE, AuditReport, CategoryResult, Finding, Severity
from integri_audit_tool.reporter import AuditReporter, NullReporter


def run_audit(
    conn: psycopg.Connection,
    config: AuditConfig,
    target_label: str,
    reporter: AuditReporter | None = None,
) -> AuditReport:
    reporter = reporter or NullReporter()
    all_categories = registry.discover_categories()

    # Out-of-scope notes (permanent tool limitations, like category 12's
    # compliance/privacy note or a category's UI-only bullet) are reported
    # regardless of --category filtering — they're properties of the tool,
    # not of a particular run, the same way category 12's note always shows
    # even when auditing a single unrelated category.
    out_of_scope_notes: list[str] = [CATEGORY_12_OUT_OF_SCOPE_NOTE]
    for category in all_categories:
        out_of_scope_notes.extend(category.out_of_scope)

    results: list[CategoryResult] = []
    for category in all_categories:
        if config.category_filter is not None and category.number not in config.category_filter:
            continue

        checks_to_run = [
            check
            for check in category.checks
            if config.check_filter is None or check.id in config.check_filter
        ]

        # When a --check filter is active and this category contributes
        # nothing to it, skip it entirely — no reporter noise (an empty 0/N
        # progress bar for every unrelated category), and no wasted
        # applicability query against the database for a category that was
        # never going to run anything anyway.
        if config.check_filter is not None and not checks_to_run:
            result = CategoryResult(category_number=category.number, category_name=category.name, status="completed")
            results.append(result)
            reporter.category_completed(category, result)
            continue

        reporter.category_ready(category, checks_to_run)

        if category.applicability is not None and not category.applicability(conn):
            reason = "Category does not apply to this database (applicability check returned False)."
            reporter.category_not_applicable(category, reason)
            result = CategoryResult(
                category_number=category.number,
                category_name=category.name,
                status="not_applicable",
                na_reason=reason,
            )
            results.append(result)
            reporter.category_completed(category, result)
            continue

        findings: list[Finding] = []
        for check in checks_to_run:
            reporter.check_started(category, check)
            try:
                check_findings = check.fn(conn, config)
                findings.extend(check_findings)
                reporter.check_succeeded(category, check, check_findings)
            except Exception as exc:  # noqa: BLE001 - one bad check must not abort the run
                reporter.check_failed(category, check, exc)
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

        result = CategoryResult(
            category_number=category.number,
            category_name=category.name,
            status="completed",
            findings=findings,
        )
        results.append(result)
        reporter.category_completed(category, result)

    report = AuditReport(
        target_label=target_label,
        generated_at=datetime.now(timezone.utc),
        category_results=results,
        out_of_scope=out_of_scope_notes,
    )
    reporter.audit_completed(report)
    return report
