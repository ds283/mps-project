#!/bin/bash

celery -A celery_node.celery beat --scheduler app.sqlalchemy_scheduler:DatabaseScheduler --loglevel=INFO
