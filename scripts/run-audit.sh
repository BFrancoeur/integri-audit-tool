#!/usr/bin/env bash
# Runs a full audit, prompting for the client's business name and writing
# the report to reports/<business-name-slug>-<unique-id>.md — so the
# filename itself identifies which client it's for, preventing an audit
# meant for one client from accidentally being sent to another.
#
# The business-name prompt and the --step "press Enter" gates below both
# live in integri-audit's own Python process (cli.py's --ask-client-name),
# not here — handing stdin off between a bash `read` and a freshly-spawned
# Python subprocess turned out to leak a buffered keystroke through under
# Git Bash/mintty (the Enter that submitted the business name was also
# silently satisfying category 1's --step gate). Keeping the whole
# interactive sequence inside one process's input() calls avoids that.
#
# Runs with --step by default: each category pauses at its readiness message
# until you press Enter, so 11 categories don't just blast through
# unattended. Pass --no-step to run the whole thing uninterrupted.
#
# Usage:
#   ./scripts/run-audit.sh [extra integri-audit run args, e.g. --no-pdf, --no-step]
#   or: ia run [extra args]
#
# Requires $INTEGRI_DSN to be set (same as every other script here).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$SCRIPT_DIR"
# --step/--ask-client-name come before "$@" so an explicit --no-step or
# --no-ask-client-name passed through still wins (Typer/Click resolve
# boolean toggle flags by last occurrence).
uv run integri-audit run --step --ask-client-name "$@"
