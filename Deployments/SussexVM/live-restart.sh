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

# Pull both distinct images in one operation; covers all services
$COMPOSE pull web1 llm_worker

# Restart all non-web services in parallel
$COMPOSE up -d --no-deps --force-recreate --remove-orphans \
    default_worker llm_worker priority_worker scheduler flower

# Rolling web restart: bring up each instance and confirm healthy before proceeding
$COMPOSE up -d --no-deps --force-recreate --remove-orphans web1
wait_for_healthy web1

$COMPOSE up -d --no-deps --force-recreate --remove-orphans web2
wait_for_healthy web2

$COMPOSE up -d --no-deps --force-recreate --remove-orphans web3
wait_for_healthy web3

docker rmi $(docker images --filter "dangling=true" -q --no-trunc) 2>/dev/null || true
