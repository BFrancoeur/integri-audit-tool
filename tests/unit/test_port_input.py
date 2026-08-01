from __future__ import annotations

import pytest
import typer

from integri_audit_tool import port_input


def test_prompt_for_port_returns_default_when_blank(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")

    assert port_input.prompt_for_port("Database port", 5432) == 5432


def test_prompt_for_port_returns_the_entered_value(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "2222")

    assert port_input.prompt_for_port("Bastion SSH port", 22) == 2222


def test_prompt_for_port_rejects_non_numeric_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "not-a-port")

    with pytest.raises(typer.Exit):
        port_input.prompt_for_port("Database port", 5432)


def test_prompt_for_port_rejects_zero(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "0")

    with pytest.raises(typer.Exit):
        port_input.prompt_for_port("Database port", 5432)


def test_prompt_for_port_rejects_negative(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "-1")

    with pytest.raises(typer.Exit):
        port_input.prompt_for_port("Database port", 5432)


def test_prompt_for_port_rejects_above_max(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "65536")

    with pytest.raises(typer.Exit):
        port_input.prompt_for_port("Database port", 5432)


def test_prompt_for_port_accepts_max_boundary(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "65535")

    assert port_input.prompt_for_port("Database port", 5432) == 65535
