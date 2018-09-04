#
# Created by David Seery on 09/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from sqlalchemy.exc import SQLAlchemyError

from ..models import db, User, TaskRecord
from ..task_queue import progress_update


def register_user_launch_tasks(celery):

    @celery.task()
    def mark_user_task_started(task_id, name):
        progress_update(task_id, TaskRecord.RUNNING, 0, 'Starting task "{name}"'.format(name=name),
                        autocommit=True)


    @celery.task(bind=True)
    def mark_user_task_ended(self, task_id, name, user_id, notify=False):
        progress_update(task_id, TaskRecord.SUCCESS, 100, 'Task "{name}" complete'.format(name=name),
                        autocommit=not notify)

        try:
            owner = User.query.filter_by(id=user_id).first()
        except SQLAlchemyError:
            db.session.commit()
            raise self.retry()

        if notify:
            owner.post_message('Task "{name}" completed successfully'.format(name=name), 'success', autocommit=True)


    @celery.task(bind=True)
    def mark_user_task_failed(self, task_id, name, user_id):
        progress_update(task_id, TaskRecord.FAILURE, 100, "Error while running task '{name}'".format(name=name))

        try:
            owner = User.query.filter_by(id=user_id).first()
        except SQLAlchemyError:
            db.session.commit()
            raise self.retry()

        owner.post_message('Task "{name}" failed to complete'.format(name=name), 'danger', autocommit=True)
