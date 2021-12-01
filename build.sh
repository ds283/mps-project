#!/usr/bin/env bash

echo "git_tag='`git log -1 --format=%h`'" > app/build_data.py
docker compose down
docker compose build --force-rm
docker rmi $(docker images --filter "dangling=true" -q --no-trunc)
docker compose up -d
