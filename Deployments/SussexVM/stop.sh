#!/usr/bin/env bash
set -euo pipefail

STACK="mpsprojects"

docker stack rm "$STACK"

# Wait for all stack services to be fully removed
echo "Waiting for stack '$STACK' to shut down..."
timeout=120
elapsed=0
while [ $elapsed -lt $timeout ]; do
    remaining=$(docker stack ps "$STACK" --format '{{.ID}}' 2>/dev/null | wc -l)
    if [ "$remaining" -eq 0 ]; then
        echo "Stack removed."
        exit 0
    fi
    echo "  $remaining task(s) still shutting down (${elapsed}s elapsed)..."
    sleep 5
    elapsed=$((elapsed + 5))
done

echo "WARNING: stack did not fully shut down within ${timeout}s" >&2
docker stack ps "$STACK"
