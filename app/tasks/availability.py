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
from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from flask import current_app, render_template
from flask_mail import Message

from ..database import db
from ..models import User, PresentationAssessment, TaskRecord, FacultyData, EnrollmentRecord, PresentationSession, \
    AssessorAttendanceData, SubmitterAttendanceData
from ..task_queue import progress_update, register_task
from ..shared.sqlalchemy import get_count

from datetime import datetime, date
from dateutil import parser


def register_availability_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def issue(self, data_id, user_id, celery_id, deadline):
        self.update_state(state='STARTED',
                          meta='Looking up PresentationAssessment record for id={id}'.format(id=data_id))

        if isinstance(deadline, str):
            deadline = parser.parse(deadline).date()
        else:
            if not isinstance(deadline, date):
                raise RuntimeError('Could not interpret "deadline" argument')

        try:
            data = db.session.query(PresentationAssessment).filter_by(id=data_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None:
            self.update_state('FAILURE', meta='Could not load PresentationAssessment record from database')
            progress_update(celery_id, TaskRecord.FAILURE, 100, "Database error", autocommit=True)
            raise Ignore()

        # first task is to build a list of faculty assessors
        # we bake this list into the PresentationAssessment record via a set of AssessorAttendanceData instances
        assessor_ids = set()

        # build list of eligible assessors for each submission period included in this assessment,
        # and merge into assessor_ids if required
        for period in data.submission_periods:
            assessors = period.assessors_list \
                .join(EnrollmentRecord, EnrollmentRecord.owner_id == FacultyData.id) \
                .filter(EnrollmentRecord.pclass_id == period.config.pclass_id,
                        EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED).all()

            for assessor in assessors:
                if assessor.id not in assessor_ids:
                    assessor_ids.add(assessor.id)

        assessor_tasks = group(attach_assessment_assessor.s(data_id, a_id) | issue_assessor_email.s(deadline) for a_id in assessor_ids)

        talk_ids = set()

        # build list of submitters for each submission period included in this assessment,
        # and merge into talk_ids
        for period in data.submission_periods:
            for talk in period.submitter_list.all():
                if talk.id not in talk_ids:
                    talk_ids.add(talk.id)

        submitter_tasks = group(attach_assessment_submitter.s(data_id, s_id) for s_id in talk_ids)

        task_chain = availability_finalize_msg.si(celery_id, data_id, deadline)

        if len(submitter_tasks) > 0:
            task_chain = attach_submitter_pre_msg.si(celery_id) | submitter_tasks | \
                         attach_submitter_post_msg.s(celery_id) | task_chain

        if len(assessor_tasks) > 0:
            task_chain = attach_assessor_pre_msg.si(celery_id) | assessor_tasks | \
                         attach_assessor_post_msg.s(celery_id, user_id) | task_chain

        return self.replace(task_chain)


    @celery.task()
    def attach_assessor_pre_msg(task_id):
        progress_update(task_id, TaskRecord.RUNNING, 20, "Attaching database records for faculty assessors ...",
                        autocommit=True)


    @celery.task(bind=True)
    def attach_assessor_post_msg(self, results, task_id, user_id):
        if isinstance(results, int):
            num_issued = results
        elif isinstance(results, list):
            num_issued = sum(results)
        else:
            self.update_state('FAILURE', 'Unexpected result type forwarded in attaching assessor records')
            raise RuntimeError('Unexpected result type forwarded in attaching assessor records')

        progress_update(task_id, TaskRecord.RUNNING, 40,
                        'Attached {n} faculty records'.format(n=num_issued, pl='' if num_issued == 1 else 's'),
                        autocommit=True)

        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise Ignore()

        if user is not None:
            user.post_message('{n} availability request{pl} issued'.format(n=num_issued, pl='' if num_issued == 1 else 's'),
                              'info', autocommit=True)

        return num_issued


    @celery.task()
    def attach_submitter_pre_msg(task_id):
        progress_update(task_id, TaskRecord.RUNNING, 60, "Attaching database records for submitters ...",
                        autocommit=True)


    @celery.task(bind=True)
    def attach_submitter_post_msg(self, results, task_id):
        if isinstance(results, int):
            num_attached = results
        elif isinstance(results, list):
            num_attached = sum(results)
        else:
            self.update_state('FAILURE', 'Unexpected result type forwarded in attaching assessor records')
            raise RuntimeError('Unexpected result type forwarded in attaching assessor records')

        progress_update(task_id, TaskRecord.RUNNING, 40,
                        'Attached {n} faculty records'.format(n=num_attached, pl='' if num_attached == 1 else 's'),
                        autocommit=True)
        return num_attached


    @celery.task(bind=True)
    def availability_finalize_msg(self, task_id, data_id, deadline):
        if isinstance(deadline, str):
            deadline = parser.parse(deadline).date()
        else:
            if not isinstance(deadline, date):
                raise RuntimeError('Could not interpret "deadline" argument')

        progress_update(task_id, TaskRecord.SUCCESS, 100, 'Availability requests issued', autocommit=False)

        try:
            data = db.session.query(PresentationAssessment).filter_by(id=data_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None:
            self.update_state('FAILURE', meta='Could not load PresentationAssessment record from database')
            raise Ignore()

        try:
            data.requested_availability = True
            data.availability_closed = False
            data.availability_deadline = deadline

            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return True


    @celery.task(bind=True, default_retry_delay=30)
    def attach_assessment_assessor(self, _result_data, data_id, assessor_id):
        try:
            data = db.session.query(PresentationAssessment).filter_by(id=data_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None:
            self.update_state('FAILURE', meta='Could not load PresentationAssessment record from database')
            raise Ignore()

        try:
            a_record = AssessorAttendanceData(assessment_id=data.id,
                                              faculty_id=assessor_id,
                                              comment=None,
                                              confirmed=False,
                                              confirmed_timestamp=None,
                                              assigned_limit=None,
                                              request_email_sent=False,
                                              request_timestamp=None,
                                              reminder_email_sent=False,
                                              last_reminder_timestamp=None)

            # assume available for all sessions by default
            for session in data.sessions:
                a_record.available.append(session)

            db.session.add(a_record)
            db.session.commit()

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            db.rollback()
            raise self.retry()

        # return ID of new assessor attendance record
        return a_record.id


    @celery.task(bind=True, default_retry_delay=30)
    def issue_assessor_email(self, a_record_id, deadline):
        if isinstance(deadline, str):
            deadline = parser.parse(deadline).date()
        else:
            if not isinstance(deadline, date):
                raise RuntimeError('Could not interpret "deadline" argument')

        try:
            a_record = db.session.query(AssessorAttendanceData).filter_by(id=a_record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if a_record is None:
            self.update_state('FAILURE', meta='Could not load AssessorAttendanceData record from database')
            raise Ignore()

        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        msg = Message(subject='Availability request for event {name}'.format(name=a_record.assessment.name),
                      sender=current_app.config['MAIL_DEFAULT_SENDER'],
                      reply_to=current_app.config['MAIL_REPLY_TO'],
                      recipients=[a_record.faculty.user.email])

        msg.body = render_template('email/scheduling/availability_request.txt', event=a_record.assessment,
                                   deadline=deadline, user=a_record.faculty.user)

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send availability request email to {r}'.format(r=', '.join(msg.recipients)))
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        return 1


    @celery.task(bind=True, default_retry_delay=30)
    def attach_assessment_submitter(self, _result_data, data_id, submitter_id):
        try:
            data = db.session.query(PresentationAssessment).filter_by(id=data_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None:
            self.update_state('FAILURE', meta='Could not load PresentationAssessment record from database')
            raise Ignore()

        try:
            s_record = SubmitterAttendanceData(assessment_id=data.id,
                                               submitter_id=submitter_id,
                                               attending=True)

            # assume available for all sessions by default
            for session in data.sessions:
                s_record.available.append(session)

            db.session.add(s_record)
            db.session.commit()

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            db.rollback()
            raise self.retry()

        # return ID of new submitters record
        return s_record.id


    @celery.task(bind=True, default_retry_delay=30)
    def adjust(self, record_id, current_year):
        self.update_state(state='STARTED',
                          meta='Looking up EnrollmentRecord for id={id}'.format(id=record_id))

        try:
            record = db.session.query(EnrollmentRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load EnrollmentRecord record from database')
            return

        if record.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED:
            adjust_enroll.apply_async(args=(record_id, current_year))
        else:
            adjust_unenroll.apply_async(args=(record_id, current_year))

        return None


    @celery.task(bind=True, default_retry_delay=30)
    def adjust_enroll(self, record_id, current_year):
        self.update_state(state='STARTED',
                          meta='Looking up EnrollmentRecord for id={id}'.format(id=record_id))

        try:
            record = db.session.query(EnrollmentRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load EnrollmentRecord record from database')
            return Ignore()

        # find all assessments that are actively searching for availability
        assessments = db.session.query(PresentationAssessment) \
            .filter_by(year=current_year, requested_availability=True, availability_closed=False).all()

        for assessment in assessments:
            eligible_assessor = False

            # determine whether this faculty member is eligible for inclusion in this assessment
            for period in assessment.submission_periods:
                assessors = period.assessors_list \
                    .join(EnrollmentRecord, EnrollmentRecord.owner_id == FacultyData.id) \
                    .filter(EnrollmentRecord.pclass_id == period.config.pclass_id,
                            EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED,
                            EnrollmentRecord.owner_id == record.owner_id)

                count = get_count(assessors)
                if count > 0:
                    eligible_assessor = True
                    break

            if eligible_assessor:
                print('Determined that {name} is an eligible assessor for assessment '
                      '"{ass_name}"'.format(name=record.owner.user.name,
                                            ass_name=assessment.name))
            else:
                print('Determined that {name} is not an eligible assessor for assessment '
                      '"{ass_name}"'.format(name=record.owner.user.name,
                                            ass_name=assessment.name))

            # if eligible but not included, fix
            if eligible_assessor and get_count(assessment.assessor_list.filter_by(faculty_id=record.owner_id)) == 0:
                print('-- Assessor {name} is eligible but has no attendance record; generating a new '
                      'one'.format(name=record.owner.user.name))
                new_record = AssessorAttendanceData(assessment_id=assessment.id,
                                                    faculty_id=record.owner_id,
                                                    comment=None,
                                                    confirmed=False,                                              assigned_limit=None,
                                                    request_email_sent=False,
                                                    request_timestamp=None,
                                                    reminder_email_sent=False,
                                                    last_reminder_timestamp=None)

                for session in assessment.sessions:
                    new_record.available.append(session)

                db.session.add(new_record)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()


    @celery.task(bind=True, default_retry_delay=30)
    def adjust_unenroll(self, record_id, current_year):
        self.update_state(state='STARTED',
                          meta='Looking up EnrollmentRecord for id={id}'.format(id=record_id))

        try:
            record = db.session.query(EnrollmentRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state('FAILURE', meta='Could not load EnrollmentRecord record from database')
            return

        # find all assessments that are actively searching for availability
        assessments = db.session.query(PresentationAssessment) \
            .filter_by(year=current_year, requested_availability=True, availability_closed=False).all()

        for assessment in assessments:
            eligible_assessor = False

            # determine whether this faculty member is eligible for inclusion in this assessment
            for period in assessment.submission_periods:
                assessors = period.assessors_list \
                    .join(EnrollmentRecord, EnrollmentRecord.owner_id == FacultyData.id) \
                    .filter(EnrollmentRecord.pclass_id == period.config.pclass_id,
                            EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED,
                            EnrollmentRecord.owner_id == record.owner_id)

                count = get_count(assessors)
                if count > 0:
                    eligible_assessor = True
                    break

            # if not eligible, but included, fix
            if not eligible_assessor and get_count(assessment.assessor_list.filter_by(faculty_id=record.owner_id)) > 0:
                record = assessment.assessor_list.filter_by(faculty_id=record.owner_id).one()
                db.session.delete(record)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()


    @celery.task(bind=True, default_retry_delay=30)
    def session_added(self, sess_id, assessment_id):
        self.update_state(state='STARTED',
                          meta='Looking up PresentationAssessment record for id={id}'.format(id=assessment_id))

        try:
            data = db.session.query(PresentationAssessment).filter_by(id=assessment_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None:
            self.update_state('FAILURE', meta='Could not load PresentationAssessment record from database')
            raise Ignore

        self.update_state(state='STARTED',
                          meta='Looking up PresentationSession record for id={id}'.format(id=sess_id))

        try:
            session = db.session.query(PresentationSession).filter_by(id=sess_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if session is None:
            self.update_state('FAILURE', meta='Could not load PresentationSession record from database')
            return

        for assessor in data.assessor_list:
            if get_count(assessor.available.filter_by(id=session.id)) == 0:
                assessor.available.append(session)

            if get_count(assessor.unavailable.filter_by(id=session.id)) > 0:
                assessor.unavailable.remove(session)

            if get_count(assessor.if_needed.filter_by(id=session.id)) > 0:
                assessor.if_needed.remove(session)

        for submitter in data.submitter_list:
            if get_count(submitter.available.filter_by(id=session.id)) == 0:
                submitter.available.append(session)

            if get_count(submitter.unavailable.filter_by(id=session.id)) > 0:
                submitter.unavailable.remove(session)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()


    @celery.task(bind=True, default_retry_delay=30)
    def reminder_email(self, assessment_id, user_id):
        self.update_state(state='STARTED',
                          meta='Looking up PresentationAssessment record for id={id}'.format(id=assessment_id))

        try:
            data = db.session.query(PresentationAssessment).filter_by(id=assessment_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None:
            self.update_state('FAILURE', meta='Could not load PresentationAssessment record from database')
            raise Ignore

        recipients = set()

        for assessor in data.assessor_list:
            if not assessor.confirmed:
                recipients.add(assessor.id)

        notify = celery.tasks['app.tasks.utilities.email_notification']

        tasks = chain(group(send_reminder_email.si(r) for r in recipients if r is not None),
                      notify.s(user_id, '{n} email notification{pl} issued', 'info'))

        raise self.replace(tasks)


    @celery.task(bind=True, default_retry_delay=30)
    def send_reminder_email(self, assessor_id):
        try:
            assessor = db.session.query(AssessorAttendanceData).filter_by(id=assessor_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if assessor is None:
            self.update_status('FAILURE', meta='Could not load AssessorAttendanceData record from database')
            raise Ignore

        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        msg = Message(subject='Reminder: availability for event {name}'.format(name=assessor.assessment.name),
                      sender=current_app.config['MAIL_DEFAULT_SENDER'],
                      reply_to=current_app.config['MAIL_REPLY_TO'],
                      recipients=[assessor.faculty.user.email])

        msg.body = render_template('email/scheduling/availability_reminder.txt', event=assessor.assessment,
                                   user=assessor.faculty.user)

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send availability reminder email to {r}'.format(r=', '.join(msg.recipients)))
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        return 1
