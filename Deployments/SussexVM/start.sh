#!/usr/bin/env bash
set -euo pipefail

STACK="mpsprojects"
STACK_FILE="/its/home/docker/mpsprojects/docker-stack.yml"

# Pull all service images before deploying
docker pull quay.io/ds283/mpsproject:master
docker pull quay.io/ds283/mpsproject-celery:master
docker pull quay.io/ds283/mpsproject-nginx:master

# Deploy (or update) the stack
docker stack deploy -c "$STACK_FILE" "$STACK" --with-registry-auth

# Wait for all replicas across all services to reach running state
echo "Waiting for all stack services to reach running state..."
timeout=180
elapsed=0
while [ $elapsed -lt $timeout ]; do
    total=$(docker stack ps "$STACK" --filter "desired-state=running" --format '{{.ID}}' 2>/dev/null | wc -l)
    running=$(docker stack ps "$STACK" --filter "desired-state=running" --format '{{.CurrentState}}' 2>/dev/null | grep -c "^Running" || true)
    if [ "$running" -ge "$total" ] && [ "$total" -gt 0 ]; then
        echo "All $total replica(s) running."
        break
    fi
    echo "  $running/$total replicas running (${elapsed}s elapsed)..."
    sleep 10
    elapsed=$((elapsed + 10))
done

if [ $elapsed -ge $timeout ]; then
    echo "WARNING: not all replicas reached running state within ${timeout}s" >&2
    docker stack ps "$STACK"
fi

# Remove dangling images
docker image prune -f
