from datetime import datetime, timezone

from integri_audit_tool.models import AuditReport, CategoryResult, Severity
from integri_audit_tool.report.markdown import render


def test_render_includes_all_required_sections(make_finding):
    report = AuditReport(
        target_label="example.db:5432",
        generated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        category_results=[
            CategoryResult(
                category_number=3,
                category_name="Indexing Strategy",
                status="completed",
                findings=[
                    make_finding(
                        category_number=3, category_name="Indexing Strategy", severity=Severity.HIGH
                    )
                ],
            ),
            CategoryResult(
                category_number=2,
                category_name="JSONB Structure & Governance",
                status="not_applicable",
                na_reason="No JSONB columns detected.",
            ),
        ],
    )

    rendered = render(report)

    assert "# Postgres Database & Search Audit Report — example.db:5432" in rendered
    assert "## Executive Summary" in rendered
    assert "## Findings Summary Table" in rendered
    assert "## Detailed Findings" in rendered
    assert "## Out of Scope / Not Assessed" in rendered
    assert "## Suggested Remediation Phases" in rendered
    assert "**N/A** — No JSONB columns detected." in rendered
    assert "Category 12: Compliance & Data Privacy" in rendered


def test_render_handles_no_findings():
    report = AuditReport(
        target_label="empty-db",
        generated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        category_results=[],
    )
    rendered = render(report)
    assert "No findings were recorded" in rendered
