#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from app.models import db, TaskRecord

from uuid import uuid4

from datetime import datetime


def register_task(name, owner_id=None, description=None):
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
                      owner_id=owner_id,
                      description=description,
                      start_date=datetime.now(),
                      status=TaskRecord.PENDING,
                      progress=None,
                      message=None)

    db.session.add(data)
    db.session.commit()

    return uuid


def progress_update(task_id, state, progress, message):

    data = TaskRecord.query.filter_by(id=task_id).first()

    if data is not None:

        data.status = state
        data.progress = progress
        data.message = message

        db.session.commit()
