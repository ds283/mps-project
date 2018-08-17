#
# Created by David Seery on 17/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from ..models import db, MatchingAttempt, TaskRecord

from ..task_queue import progress_update

from celery import chain, group

from sqlalchemy.exc import SQLAlchemyError

from datetime import datetime, timedelta


def register_matching_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def create_match(self, id):

        self.update_state(state='STARTED',
                          meta='Looking up MatchingAttempt record for id={id}'.format(id=id))

        try:
            record = db.session.query(MatchingAttempt).filter_by(id=id).first()
        except SQLAlchemyError:
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load MatchingAttempt record from database')
            return

        progress_update(record.celery_id, TaskRecord.SUCCESS, 100, 'Matching task complete', autocommit=False)

        record.finished = True
        record.success = True
        db.session.commit()
