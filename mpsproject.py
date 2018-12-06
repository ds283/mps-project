#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from app import create_app, db
from app.models import TaskRecord, Notification, MatchingAttempt, PresentationAssessment, PresentationSession, \
    AssessorAttendanceData, SubmitterAttendanceData, ScheduleAttempt
from sqlalchemy.exc import SQLAlchemyError


def migrate_availability_data():
    """
    Migrate old-style attendance data (for PresentationAssessment/PresentationSession) to new style,
    with individual records for each attendee
    :return:
    """
    assessments = db.session.query(PresentationAssessment).all()

    for assessment in assessments:
        for assessor in assessment.assessors.all():
            new_record = AssessorAttendanceData(faculty_id=assessor.id,
                                                assessment_id=assessment.id,
                                                comment=None)

            for session in assessment.sessions.all():
                if session.faculty_available(assessor.id):
                    new_record.available.append(session)
                else:
                    new_record.unavailable.append(session)

            db.session.add(new_record)

        for submitter in assessment.submitters.all():
            new_record = SubmitterAttendanceData(submitter_id=submitter.id,
                                                 assessment_id=assessment.id,
                                                 attending=not assessment.not_attending(submitter.id))

            for session in assessment.sessions.all():
                if session.submitter_available(submitter.id):
                    new_record.available.append(session)
                else:
                    new_record.unavailable.append(session)

            db.session.add(new_record)


def migrate_confirmation_data():
    """
    Migrate old-style confirmation data for PresentationAssessment (held in a separate association table)
    to new-style (held as part of the AssessorAttendanceData record)
    :return:
    """
    assessments = db.session.query(PresentationAssessment).all()

    for assessment in assessments:
        for record in assessment.assessor_list:
            if record.faculty in assessment.availability_outstanding:
                record.confirmed = False
                record.confirmed_timestamp = None
            else:
                record.confirmed = True
                record.confirmed_timestamp = None

    db.session.commit()


app, celery = create_app()

with app.app_context():
    # on restart, drop all transient task records and notifications, which will no longer have any meaning
    TaskRecord.query.delete()
    Notification.query.delete()

    # any in-progress matching attempts or scheduling attempts will have been aborted when the app crashed or exited
    try:
        in_progress_matching = MatchingAttempt.query.filter_by(celery_finished=False)
        for item in in_progress_matching:
            item.finished = True
            item.celery_finished = True
            item.outcome = MatchingAttempt.OUTCOME_NOT_SOLVED
    except SQLAlchemyError:
        pass

    try:
        in_progress_scheduling = ScheduleAttempt.query.filter_by(celery_finished=False)
        for item in in_progress_scheduling:
            item.finished = True
            item.celery_finished = True
            item.outcome = ScheduleAttempt.OUTCOME_NOT_SOLVED
    except SQLAlchemyError:
        pass

    # migrate_availability_data()
    # migrate_confirmation_data()

    db.session.commit()

# pass control to application entry point if we are the controlling script
if __name__ == '__main__':
    app.run()
