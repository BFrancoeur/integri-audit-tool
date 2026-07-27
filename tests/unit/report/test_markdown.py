from datetime import datetime, timezone

from integri_audit_tool.models import AuditReport, CategoryResult, CheckResult, Severity
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
    assert "## Tests Performed" in rendered
    assert "## Detailed Findings" in rendered
    assert "## Suggested Remediation Phases" in rendered
    assert "**N/A** — No JSONB columns detected." in rendered


def test_render_out_of_scope_category_shows_its_notes_as_body_content():
    """The Out of Scope category has no findings by design — its own out_of_scope_notes
    render as its Detailed Findings body instead of "No findings.\""""
    report = AuditReport(
        target_label="example.db:5432",
        generated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        category_results=[
            CategoryResult(
                category_number=13,
                category_name="Out of Scope",
                status="completed",
                out_of_scope_notes=["Compliance & Data Privacy — manual review only.", "Network security — n/a."],
            ),
        ],
    )

    rendered = render(report)
    detailed = rendered.split("## Detailed Findings")[1]

    assert "### 13. Out of Scope" in detailed
    assert "- Compliance & Data Privacy — manual review only." in detailed
    assert "- Network security — n/a." in detailed
    assert "No findings." not in detailed


def test_render_tests_performed_lists_every_check_and_its_outcome():
    report = AuditReport(
        target_label="example.db:5432",
        generated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        category_results=[
            CategoryResult(
                category_number=1,
                category_name="Schema",
                status="completed",
                check_results=[
                    CheckResult(
                        check_id="01.01",
                        check_slug="a",
                        description="Are foreign keys present?",
                        status="passed",
                        finding_count=0,
                    ),
                    CheckResult(
                        check_id="01.02",
                        check_slug="b",
                        description="Is there schema drift?",
                        status="findings",
                        finding_count=3,
                    ),
                    CheckResult(
                        check_id="01.03",
                        check_slug="c",
                        description="Broken check",
                        status="error",
                        finding_count=0,
                        error_message="boom",
                    ),
                ],
            ),
        ],
    )

    rendered = render(report)
    tests_section = rendered.split("## Tests Performed")[1].split("## Detailed Findings")[0]

    assert "01.01" in tests_section
    assert "Are foreign keys present?" in tests_section
    assert "✓ Passed" in tests_section
    assert "Is there schema drift?" in tests_section
    assert "Findings" in tests_section
    assert "Broken check" in tests_section
    assert "⚠ Error" in tests_section


def test_render_title_uses_client_name_and_database_name_when_available():
    report = AuditReport(
        target_label="127.0.0.1:5432/sample_company",
        generated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        category_results=[],
        client_name="Sample Company",
    )

    rendered = render(report)

    assert "# Sample Company Database and Search Audit for sample_company" in rendered
    assert "Postgres Database & Search Audit Report" not in rendered


def test_render_title_falls_back_to_generic_label_without_client_name():
    """Ad hoc single-category runs (ia-schema et al.) never prompt for a client
    name, so the title needs a sensible fallback rather than "None Database..."."""
    report = AuditReport(
        target_label="127.0.0.1:5432/sample_company",
        generated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        category_results=[],
    )

    rendered = render(report)

    assert "# Postgres Database & Search Audit Report — 127.0.0.1:5432/sample_company" in rendered


def test_render_date_has_no_timestamp():
    report = AuditReport(
        target_label="example.db:5432",
        generated_at=datetime(2026, 7, 22, 18, 24, 45, tzinfo=timezone.utc),
        category_results=[],
    )

    rendered = render(report)

    assert "_Generated: July 22, 2026_" in rendered
    assert "18:24:45" not in rendered
    assert "T" not in rendered.split("_Generated:")[1].split("_")[0]


def test_render_handles_no_findings():
    report = AuditReport(
        target_label="empty-db",
        generated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        category_results=[],
    )
    rendered = render(report)
    assert "recorded no findings" in rendered


def test_executive_summary_reads_as_prose_not_a_bracket_tagged_list(make_finding):
    finding = make_finding(
        severity=Severity.HIGH,
        title="Table without a primary key: sessions",
        business_impact="Without a primary key, rows can't be reliably deduplicated.",
    )
    report = AuditReport(
        target_label="example.db:5432",
        generated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        category_results=[
            CategoryResult(category_number=1, category_name="Schema", status="completed", findings=[finding])
        ],
    )

    rendered = render(report)
    summary = rendered.split("## Executive Summary")[1].split("## Findings Summary Table")[0]

    assert "[High]" not in summary  # no bracket-tagged severity, styled as prose instead
    assert "This audit reviewed example.db:5432" in summary
    assert "1 of these are Critical or High severity" in summary
    assert "**High — Table without a primary key: sessions.**" in summary
    assert "Without a primary key, rows can't be reliably deduplicated." in summary


def test_executive_summary_notes_when_nothing_is_critical_or_high(make_finding):
    finding = make_finding(severity=Severity.LOW)
    report = AuditReport(
        target_label="example.db:5432",
        generated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        category_results=[
            CategoryResult(category_number=1, category_name="Schema", status="completed", findings=[finding])
        ],
    )

    rendered = render(report)

    assert "None are Critical or High severity" in rendered


def test_findings_summary_table_uses_check_id_instead_of_long_category_name(make_finding):
    """The Category column used to repeat the same long category name for every row in
    that category — nothing but wasted table width. check_id is compact, unique per row,
    and points straight to the matching heading in Detailed Findings."""
    finding = make_finding(
        check_id="01.06",
        business_impact="This exact sentence should not appear in the summary table.",
    )
    report = AuditReport(
        target_label="example.db:5432",
        generated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
        category_results=[
            CategoryResult(category_number=1, category_name="Schema", status="completed", findings=[finding])
        ],
    )

    rendered = render(report)
    table_section = rendered.split("## Findings Summary Table")[1].split("## Detailed Findings")[0]

    assert "| # | Check | Finding | Severity |" in table_section
    assert "Business Impact" not in table_section
    assert "Category" not in table_section
    assert "01.06" in table_section
    assert "This exact sentence should not appear in the summary table." not in table_section
    # ...but it's still present in Detailed Findings, where full detail belongs.
    assert "This exact sentence should not appear in the summary table." in rendered
