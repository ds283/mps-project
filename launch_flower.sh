#!/bin/sh

source venv/bin/activate
while true; do
    flask db upgrade
    if [[ "$?" == "0" ]]; then
        break
    fi
    echo Upgrade command failed, retrying in 5 secs...
    sleep 5
done
celery flower -A celery_node.celery --port=5555 --scheduler app.sqlalchemy_scheduler:DatabaseScheduler --loglevel=info
