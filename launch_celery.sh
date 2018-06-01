#!/bin/sh

source venv/bin/activate
celery -A celery_node.celery worker --loglevel=info
