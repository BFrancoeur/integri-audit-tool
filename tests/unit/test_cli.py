"""Unit tests for cli.py helpers that don't need a live DB connection."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer
from rich.console import Console

from integri_audit_tool import cli, db_login, ssh_tunnel
from integri_audit_tool.cli import (
    _IncrementalReportWriter,
    _is_interactive_terminal,
    _looks_like_synthetic_db,
    _prompt_for_client_report_path,
    _slugify,
)
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
    category = CategoryModule(
        slug="schema-design-and-normalization-boundaries",
        number=1,
        name="Schema Design & Normalization Boundaries",
        checks=[],
    )
    result = CategoryResult(category_number=1, category_name=category.name, status="completed")

    assert not md_path.exists()
    writer.category_completed(category, result)

    assert md_path.exists()
    assert "Schema Design & Normalization Boundaries" in md_path.read_text(encoding="utf-8")


def test_incremental_report_writer_accumulates_across_categories_in_the_same_file(tmp_path):
    md_path = tmp_path / "audit.md"
    writer = _IncrementalReportWriter(md_path, target_label="test-db")
    finding = Finding(
        check_slug="test-finding",
        category_number=1,
        category_name="A",
        check_id="01.01",
        title="Finding from category 1",
        severity=Severity.LOW,
        observation="obs",
    )

    writer.category_completed(
        CategoryModule(slug="a", number=1, name="A", checks=[]),
        CategoryResult(category_number=1, category_name="A", status="completed", findings=[finding]),
    )
    first_write_paths = list(tmp_path.glob("*.md"))
    writer.category_completed(
        CategoryModule(slug="b", number=2, name="B", checks=[]),
        CategoryResult(category_number=2, category_name="B", status="completed"),
    )

    # Same single file throughout — no per-category file created.
    assert list(tmp_path.glob("*.md")) == first_write_paths == [md_path]
    content = md_path.read_text(encoding="utf-8")
    assert "Finding from category 1" in content
    assert "B" in content


def test_looks_like_synthetic_db_matches_the_known_local_synthetic_db():
    assert _looks_like_synthetic_db("postgresql://postgres:synthetic@127.0.0.1:55432/synthetic_client") is True


def test_looks_like_synthetic_db_false_for_a_real_client_dsn():
    assert _looks_like_synthetic_db("postgresql://user:pass@client-vps.example.com:5432/prod") is False


def test_looks_like_synthetic_db_false_for_none():
    assert _looks_like_synthetic_db(None) is False


def test_slugify_lowercases_and_hyphenates():
    assert _slugify("Acme Test Co") == "acme-test-co"


def test_slugify_collapses_non_alphanumeric_runs_and_trims_edges():
    assert _slugify("  Zota Manufacturing, Inc.!! ") == "zota-manufacturing-inc"


def test_slugify_empty_for_a_name_with_no_letters_or_digits():
    assert _slugify("!!!") == ""


def test_prompt_for_client_report_path_builds_expected_filename(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "Acme Test Co")

    path, business_name = _prompt_for_client_report_path()

    assert path.parent.resolve() == (tmp_path / "reports").resolve()
    assert path.name.startswith("acme-test-co-")
    assert path.name.endswith(".md")
    assert path.parent.is_dir()
    assert business_name == "Acme Test Co"


def test_prompt_for_client_report_path_rejects_empty_name(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "   ")

    with pytest.raises(typer.Exit):
        _prompt_for_client_report_path()


def test_prompt_for_client_report_path_rejects_name_with_no_letters_or_digits(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "!!!")

    with pytest.raises(typer.Exit):
        _prompt_for_client_report_path()


def test_acquire_connection_plain_dsn_path(mocker):
    fake_conn = mocker.Mock()
    mock_connect_read_only = mocker.patch.object(cli, "connect_read_only")
    mock_connect_read_only.return_value.__enter__ = mocker.Mock(return_value=fake_conn)
    mock_connect_read_only.return_value.__exit__ = mocker.Mock(return_value=False)
    console = Console(stderr=True)

    with cli._acquire_connection("postgresql://user:pass@host:5432/dbname", False, console) as (
        conn,
        target_label,
    ):
        assert conn is fake_conn
        assert target_label == "postgresql://host:5432/dbname"  # credentials stripped


def test_acquire_connection_requires_dsn_or_ssh_connect():
    console = Console(stderr=True)

    with pytest.raises(typer.Exit):
        with cli._acquire_connection(None, False, console):
            pass


def test_acquire_connection_ssh_path_prints_success_and_builds_target_label(mocker):
    fake_conn = mocker.Mock()
    tunnel_config = ssh_tunnel.SshTunnelConfig(
        bastion_host="bastion.example.com",
        bastion_port=22,
        username="auditor",
        key_path=Path("/tmp/key.pem"),
        remote_host="10.0.0.5",
        remote_port=5432,
    )
    mocker.patch.object(cli.ssh_tunnel, "prompt_for_ssh_tunnel_config", return_value=tunnel_config)
    mock_open_tunnel = mocker.patch.object(cli.ssh_tunnel, "open_tunnel")
    mock_open_tunnel.return_value.__enter__ = mocker.Mock(return_value=54321)
    mock_open_tunnel.return_value.__exit__ = mocker.Mock(return_value=False)

    login_config = db_login.DbLoginConfig(
        host="127.0.0.1", port=54321, username="auditor", password="x", database="synthetic_client"
    )
    mocker.patch.object(cli.db_login, "prompt_for_db_login", return_value=login_config)
    mock_connect = mocker.patch.object(cli.db_login, "connect")
    mock_connect.return_value.__enter__ = mocker.Mock(return_value=fake_conn)
    mock_connect.return_value.__exit__ = mocker.Mock(return_value=False)

    console = Console(stderr=True)
    with cli._acquire_connection(None, True, console) as (conn, target_label):
        assert conn is fake_conn
        # The *real* remote host/port a client would recognize, not the
        # ephemeral local tunnel port (54321) — that would be meaningless
        # in a report.
        assert target_label == "10.0.0.5:5432/synthetic_client"

    cli.db_login.prompt_for_db_login.assert_called_once_with(default_host="127.0.0.1", default_port=54321)
