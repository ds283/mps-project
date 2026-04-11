#
# Created by ds283 on 18/07/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app
from flask_healthz import HealthError
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..database import db


def liveness():
    """
    Check if the program is alive.
    Currently, does not perform a check, needs implementation.
    """
    pass


def readiness():
    """
    Check all required services are reachable:
      - MariaDB (SQL database)
      - Redis (cache / broker)
      - MongoDB (session store)
      - Object-storage buckets (MinIO/S3)
      - Celery workers (at least one must be responding)
    Raises HealthError if any check fails.
    """
    # --- MariaDB ---
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError as e:
        raise HealthError(f"Can't connect to the SQL database: {e}")

    # --- Redis ---
    try:
        redis_client = current_app.config.get("REDIS_SESSION")
        if redis_client is None:
            raise HealthError("Redis client is not configured")
        redis_client.ping()
    except RedisError as e:
        raise HealthError(f"Can't connect to Redis: {e}")

    # --- MongoDB ---
    try:
        mongo_client = current_app.config.get("SESSION_MONGODB")
        if mongo_client is None:
            raise HealthError("MongoDB client is not configured")
        mongo_client.admin.command("ping")
    except PyMongoError as e:
        raise HealthError(f"Can't connect to MongoDB: {e}")

    # --- Object-storage buckets ---
    buckets = current_app.config.get("OBJECT_STORAGE_BUCKETS", {})
    for bucket_key, store in buckets.items():
        try:
            store.ping()
        except Exception as e:
            raise HealthError(f"Object bucket '{bucket_key}' is not accessible: {e}")

    # --- Celery workers ---
    # Broadcasts a ping over the broker and waits up to 2 s for any worker to reply.
    # If no workers respond the endpoint reports unhealthy.
    try:
        celery = current_app.extensions.get("celery")
        if celery is None:
            raise HealthError("Celery is not configured")
        inspector = celery.control.inspect(timeout=2.0)
        ping_result = inspector.ping()
        if not ping_result:
            raise HealthError("No Celery workers are responding")
    except HealthError:
        raise
    except Exception as e:
        raise HealthError(f"Cannot reach Celery workers: {e}")
