#!/bin/sh
set -e

service cron start

exec nginx -g 'daemon off;'
