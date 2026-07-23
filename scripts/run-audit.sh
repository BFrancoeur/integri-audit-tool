#!/usr/bin/env bash
# Prompts for the client's business name and runs a full audit, writing the
# report to reports/<business-name-slug>-<unique-id>.md — so the filename
# itself identifies which client it's for, preventing an audit meant for one
# client from accidentally being sent to another.
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

read -r -p "Client's business name: " business_name
if [ -z "$business_name" ]; then
    echo "Client's business name cannot be empty." >&2
    exit 1
fi

# Lowercase, collapse anything that isn't a-z/0-9 into a single hyphen, trim
# leading/trailing hyphens — safe on any filesystem, still human-readable.
slug=$(echo "$business_name" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')
if [ -z "$slug" ]; then
    echo "Client's business name must contain at least one letter or digit." >&2
    exit 1
fi

# A timestamp is a simple, always-unique numeric id with no persistent
# counter file to manage — re-running for the same client just produces a
# new file instead of colliding with or overwriting a prior audit's report.
unique_id=$(date +%Y%m%d%H%M%S)
output_path="$SCRIPT_DIR/reports/${slug}-${unique_id}.md"

cd "$SCRIPT_DIR"
# --step comes before "$@" so an explicit --no-step passed through still wins
# (Typer/Click resolve boolean toggle flags by last occurrence).
uv run integri-audit run --output "$output_path" --step "$@"
