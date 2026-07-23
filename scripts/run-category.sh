#!/usr/bin/env bash
# Run every check in one rubric category (e.g. "1"). Uses $INTEGRI_DSN unless
# --dsn is passed explicitly among the extra args.
# Usage: scripts/run-category.sh <category-number> [extra args, e.g. --dsn ... --output report.md]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <category-number> [extra args...]" >&2
    echo "  e.g. $0 1" >&2
    echo "Run scripts/list-checks.sh to see available category numbers." >&2
    exit 1
fi

category_number="$1"
shift

uv run integri-audit run --category "$category_number" "$@"
