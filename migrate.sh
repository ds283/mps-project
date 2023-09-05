#!/usr/bin/env bash

docker compose --profile migrate up -d --force-recreate --build migration
