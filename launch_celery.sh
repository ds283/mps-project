#!/bin/bash

source venv/bin/activate
celery -A celery_node.celery worker -Ofair --loglevel=INFO --max-memory-per-child=500000 -Q ${WORKER_QUEUES}
