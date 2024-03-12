#!/bin/bash

celery -A celery_node.celery worker -Ofair --loglevel=INFO -E --concurrency=4 --max-memory-per-child=800000 -Q ${WORKER_QUEUES}
