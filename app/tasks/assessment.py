#
# Created by David Seery on 2018-12-18.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app

from sqlalchemy.exc import SQLAlchemyError

from celery.exceptions import Ignore

from ..database import db
from ..models import User, SubmittingStudent, PresentationAssessment, SubmitterAttendanceData
from ..shared.sqlalchemy import get_count


def register_assessment_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def adjust_submitter(self, submitter_id, current_year):
        self.update_state(state='STARTED',
                          meta={'msg': 'Looking up SubmittingStudent record for id={id}'.format(id=submitter_id)})

        try:
            submitter = db.session.query(SubmittingStudent).filter_by(id=submitter_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if submitter is None:
            self.update_state('FAILURE', meta={'msg': 'Could not load SubmittingStudent record from database'})
            raise Ignore()

        # find all assessments that are active this year and for which feedback is still open
        assessments = db.session.query(PresentationAssessment) \
            .filter_by(year=current_year, feedback_open=True).all()

        commit = False
        for assessment in assessments:
            for rec in submitter.records:
                if get_count(assessment.submission_periods.filter_by(id=rec.period_id)) > 0:
                    if get_count(assessment.submitter_list.filter_by(submitter_id=rec.id)) == 0:
                        data = SubmitterAttendanceData(submitter_id=rec.id,
                                                       assessment_id=assessment.id,
                                                       attending=True)

                        for session in assessment.sessions:
                            data.available.append(session)

                        db.session.add(data)
                        commit = True

        if commit:
            db.session.commit()
