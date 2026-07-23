#!/usr/bin/env bash
# Spins up a persistent, local Postgres container pre-loaded with a messy,
# realistic-looking schema (scripts/synthetic-db/seed.sql) — deliberately
# tripping findings across most of the 11 automated rubric categories — so
# checks can be run and re-run by hand (ia-* aliases, run-check.sh,
# run-category.sh) without needing a real client database.
#
# Usage:
#   ./scripts/setup-synthetic-db.sh             # create if missing, else reuse as-is
#   ./scripts/setup-synthetic-db.sh --recreate   # tear down and rebuild fresh
#
# Prints the DSN to export as $INTEGRI_DSN when done.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER_NAME="integri-synthetic-db"
POSTGRES_PORT=55432
POSTGRES_DB="synthetic_client"
POSTGRES_PASSWORD="synthetic"
DSN="postgresql://postgres:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT}/${POSTGRES_DB}"

if [ "${1:-}" = "--recreate" ]; then
    echo "Removing existing '$CONTAINER_NAME' container (if any)..."
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER_NAME")" != "true" ]; then
        echo "Starting existing '$CONTAINER_NAME' container..."
        docker start "$CONTAINER_NAME" >/dev/null
        sleep 2
    fi
    echo "Synthetic database already set up — reusing it as-is."
    echo "(Pass --recreate to wipe it and rebuild from scratch.)"
    echo ""
    echo "  export INTEGRI_DSN=\"$DSN\""
    echo ""
    exit 0
fi

# autovacuum=off cluster-wide (not a per-table reloption) keeps the seeded
# dead-tuple bloat on `sessions` visible indefinitely for repeated manual
# testing — autovacuum would otherwise clean it up within its default
# 1-minute naptime and make the 07.04/10.03 bloat findings flaky.
echo "Creating '$CONTAINER_NAME' container (postgres:16-alpine, port $POSTGRES_PORT)..."
docker run -d \
    --name "$CONTAINER_NAME" \
    -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
    -e POSTGRES_DB="$POSTGRES_DB" \
    -p "127.0.0.1:${POSTGRES_PORT}:5432" \
    postgres:16-alpine \
    -c shared_preload_libraries=pg_stat_statements \
    -c pg_stat_statements.track=all \
    -c autovacuum=off \
    >/dev/null

echo "Waiting for Postgres to accept connections..."
until docker exec "$CONTAINER_NAME" pg_isready -U postgres >/dev/null 2>&1; do
    sleep 1
done
sleep 1

echo "Loading synthetic schema and data..."
docker exec -i "$CONTAINER_NAME" psql -U postgres -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -q \
    < "$SCRIPT_DIR/synthetic-db/seed.sql" >/dev/null

echo "Generating representative query traffic (so pg_stat_statements-based checks have something to find)..."
{
    for _ in $(seq 1 150); do
        id=$(( (RANDOM % 200) + 1 ))
        echo "SELECT * FROM orders WHERE id = $id;"
    done
    echo "SELECT * FROM orders ORDER BY id OFFSET 50 LIMIT 20;"
    echo "SELECT pg_sleep(1.2);"
    for _ in $(seq 1 15); do
        id=$(( (RANDOM % 150) + 1 ))
        echo "SELECT * FROM products WHERE id = $id;"
    done
} | docker exec -i "$CONTAINER_NAME" psql -U postgres -d "$POSTGRES_DB" -q >/dev/null

echo ""
echo "Synthetic database ready."
echo ""
echo "  export INTEGRI_DSN=\"$DSN\""
echo ""
echo "Then run checks against it, e.g.:"
echo "  uv run integri-audit list-checks"
echo "  ia-schema                    # or ./scripts/run-category.sh 1"
echo "  ./scripts/run-check.sh 02.03"
echo ""
echo "Tear it down with: ./scripts/teardown-synthetic-db.sh"
