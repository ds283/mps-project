#!/bin/bash

celery -A celery_node.celery flower --port=5000 --scheduler app.sqlalchemy_scheduler:DatabaseScheduler --loglevel=info
