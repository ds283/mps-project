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
    Check that the three services the web container cannot function without are reachable:
      - MariaDB (SQL database)
      - Redis (cache / session broker)
      - MongoDB (session store)

    Object-storage (MinIO/S3) and Celery workers are intentionally excluded. A storage outage
    degrades specific features but does not prevent the web tier from serving requests; marking
    the web container unhealthy for a storage failure causes Swarm to kill it unnecessarily.
    Celery worker health is monitored separately by each worker's own healthcheck.
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
