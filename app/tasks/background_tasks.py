#
# Created by David Seery on 13/10/2022.
# Copyright (c) 2022 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import TaskRecord


def register_background_tasks(celery):
    @celery.task(bind=True)
    def prune_background_tasks(self, duration=6, interval="weeks"):
        self.update_state(state="STARTED")

        # get current date
        now = datetime.now()

        # construct a timedelta object corresponding to the specified duration
        delta = timedelta(**{interval: duration})

        # find the cutoff date; finished tasks older than this should be pruned
        limit = now - delta

        try:
            db.session.query(TaskRecord).filter(
                and_(
                    or_(
                        TaskRecord.status == TaskRecord.SUCCESS,
                        TaskRecord.status == TaskRecord.FAILURE,
                        TaskRecord.status == TaskRecord.TERMINATED,
                    ),
                    TaskRecord.start_date < limit,
                )
            ).delete()

            db.session.commit()  # intentionally not logged: periodic maintenance task

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError exception in prune_background_tasks()", exc_info=e
            )
            raise self.retry()

        # Terminate stale non-terminal tasks: any task still in PENDING or RUNNING state
        # that has not been updated in the last 48 hours is considered orphaned.
        stale_limit = now - timedelta(hours=48)

        try:
            stale_tasks = (
                db.session.query(TaskRecord)
                .filter(
                    or_(
                        TaskRecord.status == TaskRecord.PENDING,
                        TaskRecord.status == TaskRecord.RUNNING,
                    ),
                    or_(
                        # last_updated is set: use it
                        and_(
                            TaskRecord.last_updated.isnot(None),
                            TaskRecord.last_updated < stale_limit,
                        ),
                        # last_updated never set: fall back to start_date
                        and_(
                            TaskRecord.last_updated.is_(None),
                            TaskRecord.start_date < stale_limit,
                        ),
                    ),
                )
                .all()
            )

            for task in stale_tasks:
                task.status = TaskRecord.TERMINATED
                task.message = "Task terminated (no progress for 48 hours)"
                task.last_updated = now

            if stale_tasks:
                db.session.commit()  # intentionally not logged: periodic maintenance task

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError exception terminating stale tasks in prune_background_tasks()", exc_info=e
            )
            raise self.retry()

        self.update_state(state="FINISHED")
