#
# Created by David Seery on 2018-10-03.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from celery import group, chain
from sqlalchemy.exc import SQLAlchemyError

from ..models import db, User, PresentationAssessment, TaskRecord, FacultyData, EnrollmentRecord
from ..task_queue import progress_update
from ..shared.sqlalchemy import get_count


def register_availability_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def issue(self, data_id, user_id, celery_id):
        self.update_state(state='STARTED',
                          meta='Looking up PresentationAssessment record for id={id}'.format(id=data_id))

        try:
            data = db.session.query(PresentationAssessment).filter_by(id=data_id).first()
        except SQLAlchemyError:
            raise self.retry()

        if data is None:
            self.update_state('FAILURE', meta='Could not load PresentationAssessment record from database')
            progress_update(celery_id, TaskRecord.FAILURE, 100, "Database error", autocommit=True)
            return

        progress_update(celery_id, TaskRecord.RUNNING, 10, "Building list of faculty assessors...", autocommit=True)

        try:
            # first task is to build a list of faculty assessors
            for period in data.submission_periods:

                assessors = period.assessors_list \
                    .join(EnrollmentRecord, EnrollmentRecord.owner_id == FacultyData.id) \
                    .filter(EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED).all()

                for assessor in assessors:
                    if assessor not in data.assessors:
                        data.assessors.append(assessor)

            db.session.commit()
        except SQLAlchemyError:
            raise self.retry()

        progress_update(celery_id, TaskRecord.RUNNING, 50, "Generating availability requests...", autocommit=True)

        try:
            # second task is to copy this to the list of faculty who have outstanding responses
            data.availability_outstanding = data.assessors
            db.session.commit()
        except SQLAlchemyError:
            raise self.retry()

        progress_update(celery_id, TaskRecord.RUNNING, 80, "Filling default availabilities...", autocommit=True)

        try:
            # third, we assume everyone is available by default
            for assessor in data.assessors:
                for session in data.sessions:
                    if assessor not in session.faculty:
                        session.faculty.append(assessor)

            db.session.commit()
        except SQLAlchemyError:
            raise self.retry()

        progress_update(celery_id, TaskRecord.SUCCESS, 100, 'Availability requests issued', autocommit=False)

        try:
            user = db.session.query(User).filter_by(id=user_id).first()

            if user is not None:
                user.post_message('{n} availability requests issued'.format(n=get_count(data.assessors)),
                                  'info', autocommit=True)
        except SQLAlchemyError:
            pass
