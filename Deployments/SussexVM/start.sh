#!/usr/bin/env bash
set -euo pipefail

COMPOSE="docker-compose -f /its/home/docker/mpsprojects/docker-compose.yml -p mpsprojects"
PROJECT="mpsprojects"

wait_for_healthy() {
    local service="$1"
    local container="${PROJECT}_${service}_1"
    local elapsed=0
    local timeout=120

    echo "Waiting for ${service} to become healthy..."
    while [ $elapsed -lt $timeout ]; do
        status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "unknown")
        case "$status" in
            healthy)
                echo "${service} is healthy."
                return 0
                ;;
            unhealthy)
                echo "  ${service}: unhealthy at ${elapsed}s — still waiting..." ;;
            *)
                echo "  ${service}: ${status} (${elapsed}s elapsed)" ;;
        esac
        sleep 5
        elapsed=$((elapsed + 5))
    done
    echo "WARNING: ${service} did not become healthy within ${timeout}s, proceeding anyway" >&2
}

# Pull all images before taking the stack down to minimise downtime
$COMPOSE pull

# Bring everything down cleanly
$COMPOSE down --remove-orphans

# Start all services
$COMPOSE up -d

# Wait for web services to pass their health checks before declaring success
wait_for_healthy web1
wait_for_healthy web2
wait_for_healthy web3

docker rmi $(docker images --filter "dangling=true" -q --no-trunc) 2>/dev/null || true
