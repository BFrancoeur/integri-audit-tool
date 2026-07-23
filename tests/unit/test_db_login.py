from __future__ import annotations

import pytest
import typer

from integri_audit_tool import db_login


def _answers(monkeypatch, values: list[str]) -> None:
    it = iter(values)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


def test_prompt_for_db_login_happy_path(monkeypatch):
    _answers(monkeypatch, ["10.0.0.5", "5433", "auditor", "synthetic_client"])
    monkeypatch.setattr(db_login.getpass, "getpass", lambda prompt="": "hunter2")

    config = db_login.prompt_for_db_login(default_host="127.0.0.1", default_port=5432)

    assert config.host == "10.0.0.5"
    assert config.port == 5433
    assert config.username == "auditor"
    assert config.password == "hunter2"
    assert config.database == "synthetic_client"


def test_prompt_for_db_login_uses_defaults_when_blank(monkeypatch):
    _answers(monkeypatch, ["", "", "auditor", "synthetic_client"])
    monkeypatch.setattr(db_login.getpass, "getpass", lambda prompt="": "hunter2")

    config = db_login.prompt_for_db_login(default_host="127.0.0.1", default_port=54321)

    assert config.host == "127.0.0.1"
    assert config.port == 54321


def test_prompt_for_db_login_rejects_empty_username(monkeypatch):
    _answers(monkeypatch, ["", "", ""])

    with pytest.raises(typer.Exit):
        db_login.prompt_for_db_login(default_host="127.0.0.1", default_port=5432)


def test_prompt_for_db_login_rejects_empty_database(monkeypatch):
    _answers(monkeypatch, ["", "", "auditor", ""])
    monkeypatch.setattr(db_login.getpass, "getpass", lambda prompt="": "hunter2")

    with pytest.raises(typer.Exit):
        db_login.prompt_for_db_login(default_host="127.0.0.1", default_port=5432)


def test_build_dsn_percent_encodes_special_characters():
    config = db_login.DbLoginConfig(
        host="127.0.0.1", port=5432, username="au@ditor", password="p@ss/word", database="my db"
    )

    dsn = db_login.build_dsn(config)

    assert dsn == "postgresql://au%40ditor:p%40ss%2Fword@127.0.0.1:5432/my%20db"


def test_connect_delegates_to_connect_read_only_with_built_dsn(mocker):
    fake_conn = mocker.Mock()
    mock_connect_read_only = mocker.patch.object(db_login, "connect_read_only")
    mock_connect_read_only.return_value.__enter__ = mocker.Mock(return_value=fake_conn)
    mock_connect_read_only.return_value.__exit__ = mocker.Mock(return_value=False)
    config = db_login.DbLoginConfig(
        host="127.0.0.1", port=5432, username="auditor", password="hunter2", database="synthetic_client"
    )

    with db_login.connect(config) as conn:
        assert conn is fake_conn

    mock_connect_read_only.assert_called_once_with(db_login.build_dsn(config))
