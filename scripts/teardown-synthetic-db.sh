#!/usr/bin/env bash
# Removes the synthetic database container created by setup-synthetic-db.sh.
#
# Usage:
#   ./scripts/teardown-synthetic-db.sh

set -euo pipefail

CONTAINER_NAME="integri-synthetic-db"

if ! docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    echo "No '$CONTAINER_NAME' container found — nothing to do."
    exit 0
fi

docker rm -f "$CONTAINER_NAME" >/dev/null
echo "Removed '$CONTAINER_NAME'."
