from __future__ import annotations

import subprocess

import pytest
import typer

from integri_audit_tool import ssh_tunnel


def _answers(monkeypatch, values: list[str]) -> None:
    it = iter(values)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


def test_prompt_for_ssh_tunnel_config_happy_path(monkeypatch, tmp_path):
    key_path = tmp_path / "client.pem"
    key_path.write_text("fake key material")
    _answers(
        monkeypatch,
        ["bastion.example.com", "2222", "auditor", str(key_path), "10.0.0.5", "5433"],
    )

    config = ssh_tunnel.prompt_for_ssh_tunnel_config()

    assert config.bastion_host == "bastion.example.com"
    assert config.bastion_port == 2222
    assert config.username == "auditor"
    assert config.key_path == key_path
    assert config.remote_host == "10.0.0.5"
    assert config.remote_port == 5433


def test_prompt_for_ssh_tunnel_config_defaults_ports(monkeypatch, tmp_path):
    key_path = tmp_path / "client.pem"
    key_path.write_text("fake key material")
    _answers(monkeypatch, ["bastion.example.com", "", "auditor", str(key_path), "10.0.0.5", ""])

    config = ssh_tunnel.prompt_for_ssh_tunnel_config()

    assert config.bastion_port == 22
    assert config.remote_port == 5432


def test_prompt_for_ssh_tunnel_config_rejects_empty_bastion_host(monkeypatch):
    _answers(monkeypatch, [""])

    with pytest.raises(typer.Exit):
        ssh_tunnel.prompt_for_ssh_tunnel_config()


def test_prompt_for_ssh_tunnel_config_rejects_missing_key_file(monkeypatch, tmp_path):
    missing_key = tmp_path / "does-not-exist.pem"
    _answers(monkeypatch, ["bastion.example.com", "", "auditor", str(missing_key)])

    with pytest.raises(typer.Exit):
        ssh_tunnel.prompt_for_ssh_tunnel_config()


def _config(tmp_path):
    key_path = tmp_path / "client.pem"
    key_path.write_text("fake key material")
    return ssh_tunnel.SshTunnelConfig(
        bastion_host="bastion.example.com",
        bastion_port=22,
        username="auditor",
        key_path=key_path,
        remote_host="10.0.0.5",
        remote_port=5432,
    )


def test_open_tunnel_yields_local_port_and_terminates_process_on_exit(mocker, tmp_path):
    fake_process = mocker.Mock()
    fake_process.poll.return_value = None  # still running
    mocker.patch.object(ssh_tunnel.subprocess, "Popen", return_value=fake_process)
    mocker.patch.object(ssh_tunnel, "_port_is_open", return_value=True)

    with ssh_tunnel.open_tunnel(_config(tmp_path), connect_timeout=1.0) as local_port:
        assert isinstance(local_port, int)

    fake_process.terminate.assert_called_once()


def test_open_tunnel_raises_when_ssh_exits_early(mocker, tmp_path):
    fake_process = mocker.Mock()
    fake_process.poll.return_value = 255  # already exited
    fake_process.returncode = 255
    fake_process.communicate.return_value = ("", "Permission denied (publickey).")
    mocker.patch.object(ssh_tunnel.subprocess, "Popen", return_value=fake_process)

    with pytest.raises(ssh_tunnel.SshTunnelError, match="Permission denied"):
        with ssh_tunnel.open_tunnel(_config(tmp_path), connect_timeout=1.0):
            pass

    # Not a port conflict -- retrying with a fresh port wouldn't fix a bad
    # key, so open_tunnel must give up after the first attempt.
    assert ssh_tunnel.subprocess.Popen.call_count == 1


def test_open_tunnel_retries_after_a_lost_port_allocation_race(mocker, tmp_path):
    """The first allocated port gets claimed by something else before ssh
    can bind it (ssh exits immediately with a port-bind error) -- the
    second attempt, with a freshly-allocated port, succeeds."""
    conflicted_process = mocker.Mock()
    conflicted_process.poll.return_value = 255
    conflicted_process.returncode = 255
    conflicted_process.communicate.return_value = ("", "bind: Address already in use")

    successful_process = mocker.Mock()
    successful_process.poll.return_value = None

    mocker.patch.object(
        ssh_tunnel.subprocess, "Popen", side_effect=[conflicted_process, successful_process]
    )
    mocker.patch.object(ssh_tunnel, "_port_is_open", return_value=True)

    with ssh_tunnel.open_tunnel(_config(tmp_path), connect_timeout=1.0) as local_port:
        assert isinstance(local_port, int)

    assert ssh_tunnel.subprocess.Popen.call_count == 2
    successful_process.terminate.assert_called_once()
    conflicted_process.terminate.assert_not_called()


def test_open_tunnel_gives_up_after_max_attempts_of_port_conflicts(mocker, tmp_path):
    conflicted_process = mocker.Mock()
    conflicted_process.poll.return_value = 255
    conflicted_process.returncode = 255
    conflicted_process.communicate.return_value = ("", "bind: Address already in use")
    mocker.patch.object(ssh_tunnel.subprocess, "Popen", return_value=conflicted_process)

    with pytest.raises(ssh_tunnel.SshTunnelError, match="Address already in use"):
        with ssh_tunnel.open_tunnel(_config(tmp_path), connect_timeout=1.0):
            pass

    assert ssh_tunnel.subprocess.Popen.call_count == ssh_tunnel._MAX_TUNNEL_ATTEMPTS


def test_open_tunnel_detects_process_that_died_right_after_port_looked_open(mocker, tmp_path):
    """_port_is_open() only proves *something* is listening, not that it's
    ssh's listener -- if ssh has already exited by the time the port looks
    ready, that must be treated as a lost race and retried, not trusted as
    success."""
    dead_on_arrival = mocker.Mock()
    dead_on_arrival.poll.side_effect = [None, 255]  # still running, then found dead right after "ready"
    dead_on_arrival.returncode = 255
    dead_on_arrival.communicate.return_value = ("", "some race artifact")

    successful_process = mocker.Mock()
    successful_process.poll.return_value = None

    mocker.patch.object(
        ssh_tunnel.subprocess, "Popen", side_effect=[dead_on_arrival, successful_process]
    )
    mocker.patch.object(ssh_tunnel, "_port_is_open", return_value=True)

    with ssh_tunnel.open_tunnel(_config(tmp_path), connect_timeout=1.0) as local_port:
        assert isinstance(local_port, int)

    assert ssh_tunnel.subprocess.Popen.call_count == 2


def test_open_tunnel_raises_on_timeout_when_port_never_opens(mocker, tmp_path):
    fake_process = mocker.Mock()
    fake_process.poll.return_value = None  # keeps running, but...
    mocker.patch.object(ssh_tunnel.subprocess, "Popen", return_value=fake_process)
    mocker.patch.object(ssh_tunnel, "_port_is_open", return_value=False)  # ...port never opens

    with pytest.raises(ssh_tunnel.SshTunnelError, match="Timed out"):
        with ssh_tunnel.open_tunnel(_config(tmp_path), connect_timeout=0.3):
            pass

    fake_process.terminate.assert_called_once()
