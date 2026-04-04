#
# Created by David Seery on 2018-10-03.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime, date, timedelta

from celery import group, chain
from dateutil import parser
from flask import current_app
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    User,
    PresentationAssessment,
    TaskRecord,
    FacultyData,
    EnrollmentRecord,
    PresentationSession,
    AssessorAttendanceData,
    SubmitterAttendanceData,
    SubmissionRecord,
    EmailTemplate,
    EmailWorkflow,
    EmailWorkflowItem,
)
from ..models.emails import encode_email_payload
from ..shared.sqlalchemy import get_count
from ..shared.workflow_logging import log_db_commit
from ..task_queue import progress_update, register_task


def register_availability_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def initialize(self, data_id, user_id, celery_id, deadline, skip_availability, availability_template_id=None):
        self.update_state(
            state="STARTED",
            meta={
                "msg": "Looking up PresentationAssessment record for id={id}".format(
                    id=data_id
                )
            },
        )

        if not skip_availability:
            if isinstance(deadline, str):
                deadline = parser.parse(deadline).date()
            else:
                if not isinstance(deadline, date):
                    raise RuntimeError('Could not interpret "deadline" argument')
        else:
            deadline = None

        try:
            assessment: PresentationAssessment = (
                db.session.query(PresentationAssessment).filter_by(id=data_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if assessment is None:
            msg = "Could not load PresentationAssessment record from database"
            current_app.logger.error(msg)
            progress_update(celery_id, TaskRecord.FAILURE, 100, "Database error", autocommit=True)
            raise Exception(msg)

        # FIRST task is to build a list of faculty assessors
        # we bake this list into the PresentationAssessment record via a set of AssessorAttendanceData instances
        assessor_ids = set()

        # build list of eligible assessors for each submission period included in this assessment,
        # and merge into assessor_ids if required.
        for period in assessment.submission_periods:
            # previously we only considered faculty who were in the assessor list for at least one project running in
            # at least one submission period, but this is too restrictive.
            # We should enrol all active users who are currently signed up for presentation assessment.
            assessors = (
                db.session.query(FacultyData)
                .join(EnrollmentRecord, EnrollmentRecord.owner_id == FacultyData.id)
                .join(User, User.id == FacultyData.id)
                .filter(
                    User.active.is_(True),
                    EnrollmentRecord.pclass_id == period.config.pclass_id,
                    EnrollmentRecord.presentations_state
                    == EnrollmentRecord.PRESENTATIONS_ENROLLED,
                )
                .all()
            )
            assessor_ids.update([assessor.id for assessor in assessors])

        if skip_availability:
            assessor_tasks = group(
                attach_assessment_assessor.s(data_id, a_id) | assessor_email_sink.s()
                for a_id in assessor_ids
            )
        else:
            assessor_tasks = group(
                attach_assessment_assessor.s(data_id, a_id)
                | issue_assessor_email.s(deadline, availability_template_id=availability_template_id)
                for a_id in assessor_ids
            )

        # SECOND task is to build list of submitters for each submission period included in this assessment,
        # and merge into talk_ids
        talk_ids = set()
        for period in assessment.submission_periods:
            for talk in period.submitter_list.all():
                if talk.owner.student.user.active and talk.id not in talk_ids:
                    talk_ids.add(talk.id)

        submitter_tasks = group(
            attach_assessment_submitter.s(data_id, s_id) for s_id in talk_ids
        )

        task_chain = availability_finalize_msg.si(
            celery_id, data_id, user_id, deadline, skip_availability
        )

        if len(submitter_tasks) > 0:
            task_chain = (
                    attach_submitter_pre_msg.si(celery_id)
                    | submitter_tasks
                    | attach_submitter_post_msg.s(celery_id)
                    | task_chain
            )

        if len(assessor_tasks) > 0:
            task_chain = (
                attach_assessor_pre_msg.si(celery_id)
                | assessor_tasks
                | attach_assessor_post_msg.s(celery_id, user_id, skip_availability)
                | task_chain
            )

        return self.replace(task_chain.on_error(availability_error.si(celery_id)))

    @celery.task()
    def availability_error(celery_id):
        progress_update(
            celery_id,
            TaskRecord.FAILURE,
            100,
            "Availability setup failed",
            autocommit=True,
        )

    @celery.task()
    def attach_assessor_pre_msg(task_id):
        progress_update(
            task_id,
            TaskRecord.RUNNING,
            20,
            "Attaching database records for faculty assessors ...",
            autocommit=True,
        )

    @celery.task(bind=True)
    def attach_assessor_post_msg(self, results, task_id, user_id, skip_availability):
        if isinstance(results, int):
            num_issued = results
        elif isinstance(results, list):
            num_issued = sum(results)
        else:
            self.update_state(
                "FAILURE",
                meta={
                    "msg": "Unexpected result type forwarded in attaching assessor records"
                },
            )
            raise RuntimeError(
                "Unexpected result type forwarded in attaching assessor records"
            )

        progress_update(
            task_id,
            TaskRecord.RUNNING,
            40,
            "Attached {n} faculty records".format(
                n=num_issued, pl="" if num_issued == 1 else "s"
            ),
            autocommit=True,
        )

        try:
            user = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise

        if not skip_availability and user is not None:
            user.post_message(
                "{n} availability request{pl} issued".format(
                    n=num_issued, pl="" if num_issued == 1 else "s"
                ),
                "info",
                autocommit=True,
            )

        return num_issued

    @celery.task()
    def attach_submitter_pre_msg(task_id):
        progress_update(
            task_id,
            TaskRecord.RUNNING,
            60,
            "Attaching database records for submitters ...",
            autocommit=True,
        )

    @celery.task(bind=True)
    def attach_submitter_post_msg(self, results, task_id):
        if isinstance(results, int):
            num_attached = results
        elif isinstance(results, list):
            num_attached = sum(results)
        else:
            self.update_state(
                "FAILURE",
                meta={
                    "msg": "Unexpected result type forwarded in attaching assessor records"
                },
            )
            raise RuntimeError(
                "Unexpected result type forwarded in attaching assessor records"
            )

        progress_update(
            task_id,
            TaskRecord.RUNNING,
            40,
            "Attached {n} submitter records".format(
                n=num_attached, pl="" if num_attached == 1 else "s"
            ),
            autocommit=True,
        )
        return num_attached

    @celery.task(bind=True)
    def availability_finalize_msg(
            self, task_id, data_id, user_id, deadline, skip_availability
    ):
        if not skip_availability:
            if isinstance(deadline, str):
                deadline = parser.parse(deadline).date()
            else:
                if not isinstance(deadline, date):
                    raise RuntimeError('Could not interpret "deadline" argument')

        else:
            deadline = None

        progress_update(
            task_id,
            TaskRecord.SUCCESS,
            100,
            "Assessor and submitter records attached",
            autocommit=False,
        )

        try:
            assessment: PresentationAssessment = (
                db.session.query(PresentationAssessment).filter_by(id=data_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if assessment is None:
            msg = "Could not load PresentationAssessment record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        try:
            if skip_availability:
                assessment.requested_availability = False
                assessment.availability_closed = False
                assessment.availability_deadline = False

                assessment.skip_availability = True
                assessment.availability_skipped_id = user_id
                assessment.availability_skipped_timestamp = datetime.now()
            else:
                assessment.requested_availability = True
                assessment.availability_closed = False
                assessment.availability_deadline = deadline

                assessment.skip_availability = False
                assessment.availability_skipped_id = None
                assessment.availability_skipped_timestamp = None

            log_db_commit(
                "Updated availability settings for assessment",
                user=user_id,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return True

    @celery.task(bind=True, default_retry_delay=30)
    def attach_assessment_assessor(self, _result_data, data_id, assessor_id):
        try:
            data = (
                db.session.query(PresentationAssessment).filter_by(id=data_id).first()
            )
            fd = db.session.query(FacultyData).filter_by(id=assessor_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None:
            msg = "Could not load PresentationAssessment record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        if fd is None:
            msg = "Could not load FacultyData record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        if not fd.user.active:
            return

        # search for an existing record with this assessment id and assessor id, to avoid entering duplicates
        a_record = (
            db.session.query(AssessorAttendanceData)
            .filter_by(assessment_id=data.id, faculty_id=assessor_id)
            .first()
        )

        if a_record is not None:
            return a_record.id

        try:
            a_record = AssessorAttendanceData(
                assessment_id=data.id,
                faculty_id=assessor_id,
                comment=None,
                confirmed=False,
                confirmed_timestamp=None,
                assigned_limit=None,
                request_email_sent=False,
                request_timestamp=None,
                reminder_email_sent=False,
                last_reminder_timestamp=None,
            )

            # assume available for all sessions by default
            # (this is especially helpful when availability collection is being skipped)
            for session in data.sessions:
                a_record.available.append(session)

            db.session.add(a_record)
            log_db_commit(
                "Attached assessor attendance record for assessment",
                endpoint=self.name,
            )

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            db.rollback()
            raise self.retry()

        # return ID of new assessor attendance record
        return a_record.id

    @celery.task(bind=True, default_retry_delay=30)
    def assessor_email_sink(self, a_record_id):
        return 1

    @celery.task(bind=True, default_retry_delay=30)
    def issue_assessor_email(self, a_record_id, deadline, availability_template_id=None):
        if isinstance(deadline, str):
            deadline = parser.parse(deadline).date()
        else:
            if not isinstance(deadline, date):
                raise RuntimeError('Could not interpret "deadline" argument')

        try:
            a_record: AssessorAttendanceData = (
                db.session.query(AssessorAttendanceData)
                .filter_by(id=a_record_id)
                .first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if a_record is None:
            msg = "Could not load AssessorAttendanceData record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        # avoid sending duplicate emails
        if a_record.request_email_sent:
            return 0

        try:
            a_record.request_email_sent = True
            a_record.request_timestamp = datetime.now()

            log_db_commit(
                "Marked availability request email as sent for assessor",
                user=a_record.faculty.user,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if availability_template_id is not None:
            template = db.session.get(EmailTemplate, availability_template_id)
        else:
            template = EmailTemplate.find_template_(EmailTemplate.SCHEDULING_AVAILABILITY_REQUEST)
        workflow = EmailWorkflow.build_(
            name=f"Scheduling availability request: {a_record.assessment.name}",
            template=template,
            defer=timedelta(hours=1),
        )
        db.session.add(workflow)
        db.session.flush()

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({"name": a_record.assessment.name}),
            body_payload=encode_email_payload({
                "event": a_record.assessment,
                "deadline": deadline,
                "user": a_record.faculty.user,
            }),
            recipient_list=[a_record.faculty.user.email],
        )
        item.workflow = workflow
        db.session.add(item)

        try:
            log_db_commit(
                "Queued availability request email workflow for assessor",
                user=a_record.faculty.user,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return 1

    @celery.task(bind=True, default_retry_delay=30)
    def attach_assessment_submitter(self, _result_data, data_id, submitter_id):
        try:
            data: PresentationAssessment = (
                db.session.query(PresentationAssessment).filter_by(id=data_id).first()
            )
            sd: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=submitter_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None:
            msg = "Could not load PresentationAssessment record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        if sd is None:
            msg = "Could not load SubmissionRecord record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        if not sd.owner.student.user.active:
            return

        # search for existing record with this assessment_id and submitted_id, to avoid adding duplicates
        s_record = (
            db.session.query(SubmitterAttendanceData)
            .filter_by(assessment_id=data.id, submitter_id=submitter_id)
            .first()
        )

        if s_record is not None:
            return s_record.id

        try:
            s_record = SubmitterAttendanceData(
                assessment_id=data.id, submitter_id=submitter_id, attending=True
            )

            # assume available for all sessions by default
            for session in data.sessions:
                s_record.available.append(session)

            db.session.add(s_record)
            log_db_commit(
                "Attached submitter attendance record for assessment",
                endpoint=self.name,
            )

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            db.rollback()
            raise self.retry()

        # return ID of new submitters record
        return s_record.id

    @celery.task(bind=True, default_retry_delay=30)
    def adjust(self, record_id, current_year):
        self.update_state(
            state="STARTED",
            meta={
                "msg": "Looking up EnrollmentRecord for id={id}".format(id=record_id)
            },
        )

        try:
            record = db.session.query(EnrollmentRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(
                "FAILURE",
                meta={"msg": "Could not load EnrollmentRecord record from database"},
            )
            return

        if record.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED:
            adjust_enroll.apply_async(args=(record_id, current_year))
        else:
            adjust_unenroll.apply_async(args=(record_id, current_year))

        return None

    @celery.task(bind=True, default_retry_delay=30)
    def adjust_enroll(self, record_id, current_year):
        self.update_state(
            state="STARTED",
            meta={
                "msg": "Looking up EnrollmentRecord for id={id}".format(id=record_id)
            },
        )

        try:
            record = db.session.query(EnrollmentRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            msg = "Could not load EnrollmentRecord record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        # find all assessments that are actively searching for availability
        assessments = (
            db.session.query(PresentationAssessment)
            .filter(
                and_(
                    PresentationAssessment.year == current_year,
                    or_(
                        PresentationAssessment.requested_availability.is_(True),
                        PresentationAssessment.skip_availability,
                    ),
                    PresentationAssessment.availability_closed.is_(False),
                )
            )
            .all()
        )

        for assessment in assessments:
            eligible_assessor = False

            # determine whether this faculty member is eligible for inclusion in this assessment
            for period in assessment.submission_periods:
                assessors = period.assessors_list.join(
                    EnrollmentRecord, EnrollmentRecord.owner_id == FacultyData.id
                ).filter(
                    EnrollmentRecord.pclass_id == period.config.pclass_id,
                    EnrollmentRecord.presentations_state
                    == EnrollmentRecord.PRESENTATIONS_ENROLLED,
                    EnrollmentRecord.owner_id == record.owner_id,
                )

                count = get_count(assessors)
                if count > 0:
                    eligible_assessor = True
                    break

            if eligible_assessor:
                print(
                    "Determined that {name} is an eligible assessor for assessment "
                    '"{ass_name}"'.format(
                        name=record.owner.user.name, ass_name=assessment.name
                    )
                )
            else:
                print(
                    "Determined that {name} is not an eligible assessor for assessment "
                    '"{ass_name}"'.format(
                        name=record.owner.user.name, ass_name=assessment.name
                    )
                )

            # if eligible but not included, fix
            if (
                    eligible_assessor
                    and get_count(
                assessment.assessor_list.filter_by(faculty_id=record.owner_id)
            )
                    == 0
            ):
                print(
                    "-- Assessor {name} is eligible but has no attendance record; generating a new one".format(
                        name=record.owner.user.name
                    )
                )
                new_record = AssessorAttendanceData(
                    assessment_id=assessment.id,
                    faculty_id=record.owner_id,
                    comment=None,
                    confirmed=False,
                    assigned_limit=None,
                    request_email_sent=False,
                    request_timestamp=None,
                    reminder_email_sent=False,
                    last_reminder_timestamp=None,
                )

                for session in assessment.sessions:
                    new_record.available.append(session)

                db.session.add(new_record)

        try:
            log_db_commit(
                "Adjusted assessor attendance records after enrolment change",
                user=record.owner.user,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def adjust_unenroll(self, record_id, current_year):
        self.update_state(
            state="STARTED",
            meta={
                "msg": "Looking up EnrollmentRecord for id={id}".format(id=record_id)
            },
        )

        try:
            record = db.session.query(EnrollmentRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            msg = "Could not load EnrollmentRecord record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        # find all assessments that are actively searching for availability
        assessments = (
            db.session.query(PresentationAssessment)
            .filter(
                and_(
                    PresentationAssessment.year == current_year,
                    or_(
                        PresentationAssessment.requested_availability.is_(True),
                        PresentationAssessment.skip_availability,
                    ),
                    PresentationAssessment.availability_closed.is_(False),
                )
            )
            .all()
        )

        for assessment in assessments:
            eligible_assessor = False

            # determine whether this faculty member is eligible for inclusion in this assessment
            for period in assessment.submission_periods:
                assessors = period.assessors_list.join(
                    EnrollmentRecord, EnrollmentRecord.owner_id == FacultyData.id
                ).filter(
                    EnrollmentRecord.pclass_id == period.config.pclass_id,
                    EnrollmentRecord.presentations_state
                    == EnrollmentRecord.PRESENTATIONS_ENROLLED,
                    EnrollmentRecord.owner_id == record.owner_id,
                )

                count = get_count(assessors)
                if count > 0:
                    eligible_assessor = True
                    break

            # if not eligible, but included, fix
            if (
                    not eligible_assessor
                    and get_count(
                assessment.assessor_list.filter_by(faculty_id=record.owner_id)
            )
                    > 0
            ):
                record = assessment.assessor_list.filter_by(
                    faculty_id=record.owner_id
                ).one()
                db.session.delete(record)

        try:
            log_db_commit(
                "Adjusted assessor attendance records after unenrolment change",
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def session_added(self, sess_id, assessment_id):
        self.update_state(
            state="STARTED",
            meta={
                "msg": "Looking up PresentationAssessment record for id={id}".format(
                    id=assessment_id
                )
            },
        )

        try:
            data: PresentationAssessment = (
                db.session.query(PresentationAssessment)
                .filter_by(id=assessment_id)
                .first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None:
            msg = "Could not load PresentationAssessment record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        self.update_state(
            state="STARTED",
            meta={
                "msg": "Looking up PresentationSession record for id={id}".format(
                    id=sess_id
                )
            },
        )

        try:
            session = (
                db.session.query(PresentationSession).filter_by(id=sess_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if session is None:
            self.update_state(
                "FAILURE",
                meta={"msg": "Could not load PresentationSession record from database"},
            )
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
            log_db_commit(
                "Updated availability records after new session added to assessment",
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def reminder_email(self, assessment_id, user_id, reminder_template_id=None):
        self.update_state(
            state="STARTED",
            meta={
                "msg": "Looking up PresentationAssessment record for id={id}".format(
                    id=assessment_id
                )
            },
        )

        try:
            data: PresentationAssessment = (
                db.session.query(PresentationAssessment)
                .filter_by(id=assessment_id)
                .first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None:
            msg = "Could not load PresentationAssessment record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        notify = celery.tasks["app.tasks.utilities.email_notification"]

        if data.skip_availability:
            self.update_state(
                "FAILURE",
                meta={
                    "msg": "Availability collection has been skipped for this PresentationAssessment"
                },
            )
            return self.replace(
                notify.si(
                    0,
                    user_id,
                    "Reminder emails cannot be sent because availability collection has been skipped for this assessment",
                    "warning",
                )
            )

        if data.availability_closed:
            self.update_state(
                "FAILURE",
                meta={
                    "msg": "Availability collection has been closed for this PresentationAssessment"
                },
            )
            return self.replace(
                notify.si(
                    0,
                    user_id,
                    "Reminder emails cannot be sent because availability collection has already been closed for this assessment",
                    "warning",
                )
            )

        recipients = set()

        for assessor in data.assessor_list:
            if not assessor.confirmed:
                recipients.add(assessor.id)

        tasks = chain(
            group(send_reminder_email.si(r, reminder_template_id=reminder_template_id) for r in recipients if r is not None),
            notify.s(user_id, "{n} email notification{pl} issued", "info"),
        )

        return self.replace(tasks)

    @celery.task(bind=True, default_retry_delay=30)
    def send_reminder_email(self, assessor_id, reminder_template_id=None):
        try:
            assessor: AssessorAttendanceData = (
                db.session.query(AssessorAttendanceData)
                .filter_by(id=assessor_id)
                .first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if assessor is None:
            msg = "Could not load AssessorAttendanceData record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        assessment: PresentationAssessment = assessor.assessment

        if assessment.skip_availability:
            return

        if assessment.availability_closed:
            return

        try:
            assessor.reminder_email_sent = True
            assessor.last_reminder_timestamp = datetime.now()

            log_db_commit(
                "Marked availability reminder email as sent for assessor",
                user=assessor.faculty.user,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if reminder_template_id is not None:
            template = db.session.get(EmailTemplate, reminder_template_id)
        else:
            template = EmailTemplate.find_template_(EmailTemplate.SCHEDULING_AVAILABILITY_REMINDER)
        workflow = EmailWorkflow.build_(
            name=f"Scheduling availability reminder: {assessor.assessment.name}",
            template=template,
            defer=timedelta(hours=1),
        )
        db.session.add(workflow)
        db.session.flush()

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({"name": assessor.assessment.name}),
            body_payload=encode_email_payload({
                "event": assessor.assessment,
                "user": assessor.faculty.user,
            }),
            recipient_list=[assessor.faculty.user.email],
        )
        item.workflow = workflow
        db.session.add(item)

        try:
            log_db_commit(
                "Queued availability reminder email workflow for assessor",
                user=assessor.faculty.user,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return 1
