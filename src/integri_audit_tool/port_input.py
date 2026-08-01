"""Shared helper for interactively collecting a TCP port number — used by
every prompt that asks for a bastion or database port (ssh_tunnel.py,
db_login.py), so a non-numeric or out-of-range entry produces a clean CLI
error instead of an unhandled traceback.
"""

from __future__ import annotations

import typer

MIN_PORT = 1
MAX_PORT = 65535


def prompt_for_port(prompt: str, default: int) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default

    try:
        port = int(raw)
    except ValueError:
        typer.echo(f"Invalid port: '{raw}' is not a number.", err=True)
        raise typer.Exit(code=1)

    if not (MIN_PORT <= port <= MAX_PORT):
        typer.echo(f"Invalid port: {port} is out of range ({MIN_PORT}-{MAX_PORT}).", err=True)
        raise typer.Exit(code=1)

    return port
