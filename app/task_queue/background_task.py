#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, flash
from ..database import db
from ..models import TaskRecord

from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from uuid import uuid4

from datetime import datetime


def register_task(name, owner=None, description=None):
    """
    Register a task using our internal task-tracking system
    (this allows progress reports to be tracked consistently across multiple Celery tasks)
    :param name: task name
    :param owner_id: owner, if any
    :param description: task description
    :return:
    """

    # generate unique ID for this task
    uuid = str(uuid4())

    data = TaskRecord(
        id=uuid,
        name=name,
        owner_id=owner.id if owner is not None else None,
        description=description,
        start_date=datetime.now(),
        status=TaskRecord.PENDING,
        progress=None,
        message=None,
    )

    try:
        db.session.add(data)
        db.session.flush()

        if data.owner is not None:
            data.owner.post_task_update(
                data.id,
                {
                    "task": data.name,
                    "state": TaskRecord.PENDING,
                    "progress": 0,
                    "message": "Awaiting scheduling...",
                },
                autocommit=False,
            )

        db.session.commit()

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not register new task due to a database error. Please contact a system administrator",
            "error",
        )

        return None

    return uuid


def progress_update(task_id, state, progress, message, autocommit=False):
    data = TaskRecord.query.filter_by(id=task_id).first()

    if data is not None:
        # update data for task record
        data.status = state
        data.progress = progress
        data.message = message
        data.last_updated = datetime.now()

        # push a notification to owning user, if there is one
        if data.owner is not None:
            remove_on_load = False
            if (
                    data.status == TaskRecord.SUCCESS
                    or data.status == TaskRecord.FAILURE
                    or data.status == TaskRecord.TERMINATED
            ):
                remove_on_load = True

            data.owner.post_task_update(
                data.id,
                {
                    "task": data.name,
                    "state": state,
                    "progress": progress,
                    "message": message,
                },
                remove_on_load=remove_on_load,
                autocommit=False,
            )

        # commit all changes
        if autocommit:
            db.session.commit()


def reconcile_background_tasks(app):
    """
    On startup, mark any TaskRecord instances in PENDING or RUNNING state as TERMINATED.
    Tasks that are genuinely still executing on a live worker will update their own
    TaskRecord via progress_update() as they proceed, overwriting the TERMINATED state.
    Tasks that were orphaned (e.g. worker died, broker restarted) will remain TERMINATED.
    """
    celery = app.extensions.get("celery")
    if celery is None:
        app.logger.warning("reconcile_background_tasks: Celery not available, skipping reconciliation")
        return

    with app.app_context():
        try:
            stale = (
                db.session.query(TaskRecord)
                .filter(or_(TaskRecord.status == TaskRecord.PENDING, TaskRecord.status == TaskRecord.RUNNING))
                .all()
            )
        except SQLAlchemyError as e:
            app.logger.exception("reconcile_background_tasks: could not query TaskRecord", exc_info=e)
            return

        if not stale:
            return

        app.logger.info(f"reconcile_background_tasks: reconciling {len(stale)} stale task(s)")
        now = datetime.now()

        for task in stale:
            try:
                state = celery.AsyncResult(task.id).state
            except Exception as e:
                app.logger.warning(f"reconcile_background_tasks: could not check Celery state for task {task.id}: {e}")
                state = "UNKNOWN"

            if state == "SUCCESS":
                task.status = TaskRecord.SUCCESS
                task.message = "Task completed (recovered on startup)"
            elif state in ("FAILURE", "REVOKED"):
                task.status = TaskRecord.FAILURE
                task.message = "Task failed (recovered on startup)"
            else:
                # PENDING (unknown), STARTED, RETRY, or unreachable — conservatively terminate.
                # If the task is still running on a live worker it will overwrite this state
                # via progress_update() as it proceeds.
                task.status = TaskRecord.TERMINATED
                task.message = "Task terminated (server restart)"

            task.last_updated = now

        try:
            db.session.commit()
            app.logger.info(f"reconcile_background_tasks: reconciliation complete")
        except SQLAlchemyError as e:
            db.session.rollback()
            app.logger.exception("reconcile_background_tasks: could not commit reconciliation", exc_info=e)
