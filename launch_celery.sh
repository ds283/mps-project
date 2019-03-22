#!/bin/bash

source venv/bin/activate
celery -A celery_node.celery worker --loglevel=info --max-memory-per-child=500000
