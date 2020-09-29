#!/usr/bin/env bash

echo "git_tag='`git log -1 --format=%h`'" > app/build_data.py
docker-compose up -d --no-deps --force-recreate --build web1
docker-compose up -d --no-deps --force-recreate --build web2
docker-compose up -d --no-deps --force-recreate --build default_worker
docker-compose up -d --no-deps --force-recreate --build priority_worker
docker-compose up -d --no-deps --force-recreate --build scheduler
docker-compose up -d --no-deps --force-recreate --build flower
docker rmi $(docker images --filter "dangling=true" -q --no-trunc)
