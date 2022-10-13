#
# Created by David Seery on 13/10/2022.
# Copyright (c) 2022 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app

from ..database import db
from ..models import TaskRecord

from datetime import datetime, timedelta

from sqlalchemy import or_, and_
from sqlalchemy.exc import SQLAlchemyError


def register_background_tasks(celery):

    @celery.task(bind=True)
    def prune_background_tasks(self, duration=6, interval='weeks'):
        self.update_state(state='STARTED')

        # get current date
        now = datetime.now()

        # construct a timedelta object corresponding to the specified duration
        delta = timedelta(**{interval: duration})

        # find the cutoff date; finished tasks older than this should be pruned
        limit = now - delta

        try:
            db.session.query(TaskRecord).filter(and_(or_(TaskRecord.status == TaskRecord.SUCCESS,
                                                         TaskRecord.status == TaskRecord.FAILURE,
                                                         TaskRecord.status == TaskRecord.TERMINATED),
                                                     TaskRecord.start_date < limit)).delete()
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception in prune_background_tasks()", exc_info=e)
            raise self.retry()

        self.update_state(state='FINISHED')

