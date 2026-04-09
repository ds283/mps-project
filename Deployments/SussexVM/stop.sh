#!/usr/bin/env bash
set -euo pipefail

COMPOSE="docker-compose -f /its/home/docker/mpsprojects/docker-compose.yml -p mpsprojects"

$COMPOSE down --remove-orphans
