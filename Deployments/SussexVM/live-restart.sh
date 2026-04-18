#!/usr/bin/env bash
set -euo pipefail

STACK="mpsprojects"
STACK_FILE="/its/home/docker/mpsprojects/docker-stack.yml"

# Pull all service images before deploying so the update is fast
docker pull quay.io/ds283/mpsproject:master
docker pull quay.io/ds283/mpsproject-celery:master
docker pull quay.io/ds283/mpsproject-nginx:master

# Redeploy the stack. Swarm performs rolling updates for each service according
# to its update_config (parallelism, delay, failure_action). Services with
# replicas=1 and no update_config (nginx, stateful services) are restarted in place.
docker stack deploy -c "$STACK_FILE" "$STACK" --with-registry-auth

# Remove dangling images left by the update
docker image prune -f
