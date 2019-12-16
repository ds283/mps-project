#!/usr/bin/env bash

echo "git_tag='`git log -1 --format=%h`'" > app/build_data.py
docker-compose down
docker-compose build --force-rm
docker-compose up
