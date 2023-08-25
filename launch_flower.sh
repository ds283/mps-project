#!/bin/bash

while true; do
    flask db upgrade
    if [[ "$?" == "0" ]]; then
        break
    fi
    echo Upgrade command failed, retrying in 5 secs...
    sleep 5
done
celery -A celery_node.celery flower --basic-auth=$FLOWER_USERNAME:$FLOWER_PASSWORD --port=5000 --scheduler app.sqlalchemy_scheduler:DatabaseScheduler --loglevel=info
