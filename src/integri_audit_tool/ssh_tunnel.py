"""Opens an SSH local port-forward tunnel to a client's database through a
bastion/jump host — the database itself is never directly SSH-accessible in
this topology; only the bastion is.

Shells out to the system `ssh` client (present via OpenSSH on virtually
every platform, including Windows) rather than adding a Python SSH
dependency — consistent with this project's existing pattern of using
system binaries (Docker, psql, pandoc) instead of bundling their
functionality as Python packages.

This module only establishes the *transport* (an encrypted tunnel to a
locally-forwarded port); it knows nothing about Postgres credentials or the
read-only connection guarantee — that's db_login.py's job, layered on top.
"""

from __future__ import annotations

import socket
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import typer

from integri_audit_tool.port_input import prompt_for_port


class SshTunnelError(RuntimeError):
    """Raised when the SSH tunnel process fails to start, exits early, or
    never becomes reachable within the connect timeout."""


class _LostPortRaceError(SshTunnelError):
    """A specific attempt's failure looks like a lost port-allocation race
    (something else grabbed the port between _find_free_local_port() and
    ssh binding it) -- open_tunnel retries with a freshly-allocated port
    when it sees this, rather than a plain SshTunnelError, where retrying
    wouldn't help (bad credentials, an unreachable host, etc.). Still a
    real SshTunnelError as far as any caller is concerned; this is purely
    an internal retry-vs-give-up signal."""


_MAX_TUNNEL_ATTEMPTS = 3
_PORT_CONFLICT_ERROR_MARKERS = ("address already in use", "cannot listen")
_DEFAULT_BASTION_SSH_PORT = 22
_DEFAULT_REMOTE_DB_PORT = 5432


def _looks_like_port_conflict(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(marker in lowered for marker in _PORT_CONFLICT_ERROR_MARKERS)


@dataclass(frozen=True)
class SshTunnelConfig:
    bastion_host: str
    bastion_port: int
    username: str
    key_path: Path
    remote_host: str
    """The database host as reachable *from the bastion's own network* —
    almost always an internal hostname/IP, not the same as bastion_host."""
    remote_port: int


def prompt_for_ssh_tunnel_config() -> SshTunnelConfig:
    """Interactively prompts for everything needed to open a tunnel to a
    client's database through a bastion/jump host. The private key is
    collected as a file path only — the tool never touches raw key
    material, just hands the path to the system ssh client.
    """
    bastion_host = input("Bastion host (SSH jump host address): ").strip()
    if not bastion_host:
        typer.echo("Bastion host cannot be empty.", err=True)
        raise typer.Exit(code=1)

    bastion_port = prompt_for_port("Bastion SSH port", _DEFAULT_BASTION_SSH_PORT)

    username = input("SSH username: ").strip()
    if not username:
        typer.echo("SSH username cannot be empty.", err=True)
        raise typer.Exit(code=1)

    key_path_raw = input("Path to SSH private key: ").strip()
    if not key_path_raw:
        typer.echo("Path to SSH private key cannot be empty.", err=True)
        raise typer.Exit(code=1)
    key_path = Path(key_path_raw).expanduser()
    if not key_path.is_file():
        typer.echo(
            f"No such file: {key_path}. Request an SSH key from IT/DBA/an authorized "
            "contact at the client's company before proceeding.",
            err=True,
        )
        raise typer.Exit(code=1)

    remote_host = input("Database host (as reachable from the bastion): ").strip()
    if not remote_host:
        typer.echo("Database host cannot be empty.", err=True)
        raise typer.Exit(code=1)

    remote_port = prompt_for_port("Database port", _DEFAULT_REMOTE_DB_PORT)

    return SshTunnelConfig(
        bastion_host=bastion_host,
        bastion_port=bastion_port,
        username=username,
        key_path=key_path,
        remote_host=remote_host,
        remote_port=remote_port,
    )


def _find_free_local_port() -> int:
    """Binding to port 0 and reading back the OS-assigned port is the
    standard way to get a free ephemeral port without racing something else
    for it between checking and using it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _attempt_open_tunnel(config: SshTunnelConfig, connect_timeout: float) -> tuple[subprocess.Popen, int]:
    """A single allocate-a-port → spawn ssh → wait-for-ready attempt. Raises
    _LostPortRaceError for failures that look like someone else won the
    port between _find_free_local_port() and ssh binding it — the only
    failure mode open_tunnel retries, since a fresh port sidesteps it. Any
    other failure (bad credentials, unreachable host, a genuine timeout)
    raises the plain SshTunnelError, since retrying wouldn't help.
    """
    local_port = _find_free_local_port()
    command = [
        "ssh",
        "-i", str(config.key_path),
        "-p", str(config.bastion_port),
        "-L", f"127.0.0.1:{local_port}:{config.remote_host}:{config.remote_port}",
        "-N",  # no remote command — this connection exists only to forward the port
        "-o", "ExitOnForwardFailure=yes",  # fail fast if the forward itself can't be set up, not just the login
        "-o", "StrictHostKeyChecking=accept-new",  # don't hang on an interactive host-key prompt
        f"{config.username}@{config.bastion_host}",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    deadline = time.monotonic() + connect_timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            _, stderr = process.communicate()
            message = (
                "SSH tunnel process exited before the forward was ready "
                f"(exit code {process.returncode}). ssh's error:\n"
                f"{stderr.strip() if stderr else '(no stderr captured)'}"
            )
            if _looks_like_port_conflict(stderr or ""):
                raise _LostPortRaceError(message)
            raise SshTunnelError(message)
        if _port_is_open(local_port):
            if process.poll() is not None:
                # The port looked ready, but ssh had already exited by the
                # time we checked — _port_is_open only proves *something*
                # is listening, not that it's ours. Treat it as a lost race
                # rather than trusting a listener we can't attribute.
                _, stderr = process.communicate()
                raise _LostPortRaceError(
                    "The SSH tunnel process exited immediately after its forward appeared ready "
                    f"(exit code {process.returncode}) — the listener on port {local_port} likely "
                    "belongs to a different process that won the port-allocation race. ssh's error:\n"
                    f"{stderr.strip() if stderr else '(no stderr captured)'}"
                )
            return process, local_port
        time.sleep(0.2)

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    raise SshTunnelError(f"Timed out after {connect_timeout}s waiting for the SSH tunnel to become ready.")


@contextmanager
def open_tunnel(config: SshTunnelConfig, connect_timeout: float = 15.0) -> Iterator[int]:
    """Opens an SSH local port-forward (-L) as a background subprocess and
    yields the local port it's listening on — the remote database is then
    reachable at 127.0.0.1:<that port> for as long as the context manager
    is open. The tunnel process is always terminated on exit, success or
    error.

    Allocating a free local port and having ssh bind that same port are two
    separate steps with an unavoidable gap between them — another process
    can claim the port in that window, and a readiness check that only
    confirms *something* is listening can't by itself prove it's ssh's
    listener. Neither gap is eliminated outright (no atomic "reserve this
    port for ssh" primitive exists); instead, a lost race is detected (ssh
    exits with a port-bind error, or has already exited by the time its
    forward looks ready) and retried with a freshly-allocated port, up to
    _MAX_TUNNEL_ATTEMPTS times.
    """
    process: subprocess.Popen | None = None
    local_port: int | None = None
    for attempt in range(1, _MAX_TUNNEL_ATTEMPTS + 1):
        try:
            process, local_port = _attempt_open_tunnel(config, connect_timeout)
            break
        except _LostPortRaceError:
            if attempt == _MAX_TUNNEL_ATTEMPTS:
                raise

    try:
        yield local_port
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
