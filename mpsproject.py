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
    AssessorAttendanceData, SubmitterAttendanceData, ScheduleAttempt, StudentData, User, ProjectClass, \
    SelectingStudent, ProjectDescription, Project
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


def populate_student_validation_data():
    """
    Populate validation state in StudentData table
    :return:
    """
    students = db.session.query(StudentData).all()

    for student in students:
        if student.validation_state is None:
            student.validation_state = StudentData.VALIDATION_QUEUED
            student.validator_id = None
            student.validated_timestamp = None

    db.session.commit()


def populate_project_validation_data():
    """
    Populate validation state in Projects table
    :return:
    """
    descriptions = db.session.query(ProjectDescription).all()

    for desc in descriptions:
        if desc.workflow_state is None:
            desc.workflow_state = ProjectDescription.WORKFLOW_APPROVAL_QUEUED
            desc.validator_id = None
            desc.validated_timestamp = None

    db.session.commit()


def populate_email_options():
    users = db.session.query(User).all()

    for user in users:
        user.group_summaries = True
        user.summary_frequency = 1

    db.session.commit()


def populate_schedule_tags():
    schedules = db.session.query(ScheduleAttempt).all()

    for s in schedules:
        if s.tag is None:
            s.tag = 'schedule_{n}'.format(n=s.id)

    db.session.commit()


def populate_new_fields():
    pclasses = db.session.query(ProjectClass).all()

    for pcl in pclasses:
        if pcl.auto_enroll_years is None:
            pcl.auto_enroll_years = ProjectClass.AUTO_ENROLL_PREVIOUS_YEAR

    selectors = db.session.query(SelectingStudent).all()
    for sel in selectors:
        if sel.convert_to_submitter is None:
            sel.convert_to_submitter = True

    db.session.commit()


def attach_JRA_projects():
    rp_pclass = db.session.query(ProjectClass).filter_by(id=2).one()
    JRA_pclass = db.session.query(ProjectClass).filter_by(id=6).one()

    projects = db.session.query(Project).all()
    for p in projects:
        if rp_pclass in p.project_classes:
            if JRA_pclass not in p.project_classes:
                p.project_classes.append(JRA_pclass)

    db.session.flush()

    descriptions = db.session.query(ProjectDescription).all()
    for d in descriptions:
        if rp_pclass in d.project_classes:
            if JRA_pclass not in d.project_classes:
                d.project_classes.append(JRA_pclass)

    db.session.commit()


app, celery = create_app()

with app.app_context():
    # on restart, drop all transient task records and notifications, which will no longer have any meaning
    TaskRecord.query.delete()
    Notification.query.delete()

    # any in-progress matching attempts or scheduling attempts will have been aborted when the app crashed or exited
    try:
        in_progress_matching = db.session.query(MatchingAttempt).filter_by(celery_finished=False)
        for item in in_progress_matching:
            item.finished = True
            item.celery_finished = True
            item.outcome = MatchingAttempt.OUTCOME_NOT_SOLVED
    except SQLAlchemyError:
        pass

    try:
        in_progress_scheduling = db.session.query(ScheduleAttempt).filter_by(celery_finished=False)
        for item in in_progress_scheduling:
            item.finished = True
            item.celery_finished = True
            item.outcome = ScheduleAttempt.OUTCOME_NOT_SOLVED
    except SQLAlchemyError:
        pass

    # reset last precompute time for all users; this will ensure that expensive views
    # are precomputed for all users when they first make contact with the web app after
    # a reset
    try:
        users = db.session.query(User).filter_by(active=True)
        for user in users:
            user.last_precompute = None
    except SQLAlchemyError:
        pass

    # migrate_availability_data()
    # migrate_confirmation_data()
    # populate_student_validation_data()
    # populate_email_options()
    # populate_schedule_tags()
    # populate_new_fields()
    # attach_JRA_projects()
    populate_project_validation_data()

    db.session.commit()

# pass control to application entry point if we are the controlling script
if __name__ == '__main__':
    app.run()
