"""Orchestrates a full audit run: discover categories, run checks, assemble the report."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import psycopg

from integri_audit_tool import registry
from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import AuditReport, CategoryResult, CheckResult, Finding, Severity
from integri_audit_tool.reporter import AuditReporter, NullReporter

_CHECK_ID_FORMAT = "{category_number:02d}.{rubric_bullet:02d}"
"""Format for a check's displayed "NN.NN" id: its category's current display
number (computed at run time from _CATEGORY_ORDER) and the check's authored
rubric_bullet (its bullet number within the category's rubric checklist)."""


def _display_check_id(category_number: int, rubric_bullet: int) -> str:
    return _CHECK_ID_FORMAT.format(category_number=category_number, rubric_bullet=rubric_bullet)


def _matches_check_filter(check: "registry.Check", check_id: str, check_filter: set[str] | None) -> bool:
    return check_filter is None or check.slug in check_filter or check_id in check_filter


def run_audit(
    conn: psycopg.Connection,
    config: AuditConfig,
    target_label: str,
    reporter: AuditReporter | None = None,
    client_name: str | None = None,
) -> AuditReport:
    reporter = reporter or NullReporter()
    all_categories = registry.discover_categories()

    # Out-of-scope notes (permanent tool limitations, like a category's
    # UI-only bullet) are collected from every category regardless of
    # --category filtering — they're properties of the tool, not of a
    # particular run, and are always shown via the Out of Scope category
    # below, whether or not that category's own filter would otherwise
    # exclude it.
    out_of_scope_notes: list[str] = []
    for category in all_categories:
        out_of_scope_notes.extend(category.out_of_scope)

    out_of_scope_category = next((c for c in all_categories if c.out_of_scope_only), None)
    runnable_categories = [c for c in all_categories if not c.out_of_scope_only]

    results: list[CategoryResult] = []
    for category in runnable_categories:
        if config.category_filter is not None and category.number not in config.category_filter:
            continue

        checks_to_run = [
            check
            for check in category.checks
            if _matches_check_filter(
                check, _display_check_id(category.number, check.rubric_bullet), config.check_filter
            )
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
        check_results: list[CheckResult] = []
        for check in checks_to_run:
            check_id = _display_check_id(category.number, check.rubric_bullet)
            reporter.check_started(category, check)
            try:
                check_findings = [
                    dataclasses.replace(
                        finding,
                        category_number=category.number,
                        category_name=category.name,
                        check_id=check_id,
                    )
                    for finding in check.fn(conn, config)
                ]
                findings.extend(check_findings)
                reporter.check_succeeded(category, check, check_findings)
                check_results.append(
                    CheckResult(
                        check_id=check_id,
                        check_slug=check.slug,
                        description=check.description,
                        status="findings" if check_findings else "passed",
                        finding_count=len(check_findings),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - one bad check must not abort the run
                reporter.check_failed(category, check, exc)
                findings.append(
                    Finding(
                        check_slug=check.slug,
                        category_number=category.number,
                        category_name=category.name,
                        check_id=check_id,
                        title=f"Check {check_id} could not be run",
                        severity=Severity.INFORMATIONAL,
                        observation=f"{check.description}\n\nThe check raised an error and was skipped: {exc}",
                    )
                )
                check_results.append(
                    CheckResult(
                        check_id=check_id,
                        check_slug=check.slug,
                        description=check.description,
                        status="error",
                        finding_count=0,
                        error_message=str(exc),
                    )
                )

        result = CategoryResult(
            category_number=category.number,
            category_name=category.name,
            status="completed",
            findings=findings,
            check_results=check_results,
        )
        results.append(result)
        reporter.category_completed(category, result)

    if out_of_scope_category is not None:
        reporter.category_ready(out_of_scope_category, [])
        out_of_scope_result = CategoryResult(
            category_number=out_of_scope_category.number,
            category_name=out_of_scope_category.name,
            status="completed",
            out_of_scope_notes=out_of_scope_notes,
        )
        results.append(out_of_scope_result)
        reporter.category_completed(out_of_scope_category, out_of_scope_result)

    report = AuditReport(
        target_label=target_label,
        generated_at=datetime.now(timezone.utc),
        category_results=results,
        client_name=client_name,
    )
    reporter.audit_completed(report)
    return report
