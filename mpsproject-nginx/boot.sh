#!/bin/sh
set -e

anacron -s
service cron start

exec nginx -g 'daemon off;'
