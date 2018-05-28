#!/bin/sh

source venv/bin/activate
celery -A mpsproject.celery worker --loglevel=info
