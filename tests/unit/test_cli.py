"""Unit tests for cli.py helpers that don't need a live DB connection."""

from __future__ import annotations

from rich.console import Console

from integri_audit_tool.cli import _is_interactive_terminal


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
