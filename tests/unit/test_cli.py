"""Unit tests for cli.py helpers that don't need a live DB connection."""

from __future__ import annotations

from rich.console import Console

from integri_audit_tool.cli import _IncrementalReportWriter, _is_interactive_terminal
from integri_audit_tool.models import CategoryResult, Finding, Severity
from integri_audit_tool.registry import CategoryModule


def test_is_interactive_terminal_true_when_console_reports_terminal():
    console = Console(stderr=True, force_terminal=True)
    assert _is_interactive_terminal(console) is True


def test_is_interactive_terminal_false_when_neither_signal_present(monkeypatch):
    monkeypatch.delenv("MSYSTEM", raising=False)
    console = Console(stderr=True, force_terminal=False)
    assert _is_interactive_terminal(console) is False


def test_is_interactive_terminal_true_under_msys_even_if_isatty_is_false(monkeypatch):
    """Git Bash's mintty reports isatty() as False even when interactive —
    MSYSTEM is the fallback signal that catches that case."""
    monkeypatch.setenv("MSYSTEM", "MINGW64")
    console = Console(stderr=True, force_terminal=False)
    assert _is_interactive_terminal(console) is True


def test_incremental_report_writer_creates_file_after_first_category(tmp_path):
    md_path = tmp_path / "audit.md"
    writer = _IncrementalReportWriter(md_path, target_label="test-db")
    category = CategoryModule(number=1, name="Schema Design & Normalization Boundaries", checks=[])
    result = CategoryResult(category_number=1, category_name=category.name, status="completed")

    assert not md_path.exists()
    writer.category_completed(category, result)

    assert md_path.exists()
    assert "Schema Design & Normalization Boundaries" in md_path.read_text(encoding="utf-8")


def test_incremental_report_writer_accumulates_across_categories_in_the_same_file(tmp_path):
    md_path = tmp_path / "audit.md"
    writer = _IncrementalReportWriter(md_path, target_label="test-db")
    finding = Finding(
        category_number=1,
        category_name="A",
        check_id="01.01",
        title="Finding from category 1",
        severity=Severity.LOW,
        observation="obs",
    )

    writer.category_completed(
        CategoryModule(number=1, name="A", checks=[]),
        CategoryResult(category_number=1, category_name="A", status="completed", findings=[finding]),
    )
    first_write_paths = list(tmp_path.glob("*.md"))
    writer.category_completed(
        CategoryModule(number=2, name="B", checks=[]),
        CategoryResult(category_number=2, category_name="B", status="completed"),
    )

    # Same single file throughout — no per-category file created.
    assert list(tmp_path.glob("*.md")) == first_write_paths == [md_path]
    content = md_path.read_text(encoding="utf-8")
    assert "Finding from category 1" in content
    assert "B" in content
