#!/bin/bash

source venv/bin/activate
while true; do
    flask db upgrade
    if [[ "$?" == "0" ]]; then
        break
    fi
    echo Upgrade command failed, retrying in 5 secs...
    sleep 5
done
celery -A celery_node.celery flower --port=5000 --scheduler app.sqlalchemy_scheduler:DatabaseScheduler --loglevel=info
