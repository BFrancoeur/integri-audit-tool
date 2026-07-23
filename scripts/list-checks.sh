#!/usr/bin/env bash
# List every implemented check id and description. No database connection needed.
# Usage: scripts/list-checks.sh [-- extra args passed to `integri-audit list-checks`]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

uv run integri-audit list-checks "$@"
