#!/bin/sh

source venv/bin/activate
celery -A mpsproject.celery beat --loglevel=info
