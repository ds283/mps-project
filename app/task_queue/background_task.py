#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from ..database import db
from ..models import TaskRecord

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

    data = TaskRecord(id=uuid,
                      name=name,
                      owner_id=owner.id if owner is not None else None,
                      description=description,
                      start_date=datetime.now(),
                      status=TaskRecord.PENDING,
                      progress=None,
                      message=None)

    db.session.add(data)
    db.session.flush()

    if data.owner is not None:

        data.owner.post_task_update(data.id, {'task': data.name, 'state': TaskRecord.PENDING,
                                               'progress': 0, 'message': 'Awaiting scheduling...'},
                                    autocommit=False)

    db.session.commit()

    return uuid


def progress_update(task_id, state, progress, message, autocommit=False):

    data = TaskRecord.query.filter_by(id=task_id).first()

    if data is not None:

        # update data for task record
        data.status = state
        data.progress = progress
        data.message = message

        # push a notification to owning user, if there is one
        if data.owner is not None:

            remove_on_load = False
            if data.status == TaskRecord.SUCCESS \
                    or data.status == TaskRecord.FAILURE \
                    or data.status == TaskRecord.TERMINATED:
                remove_on_load = True

            data.owner.post_task_update(data.id, {'task': data.name, 'state': state,
                                                   'progress': progress, 'message': message},
                                        remove_on_load=remove_on_load, autocommit=False)

        # commit all changes
        if autocommit:
            db.session.commit()
