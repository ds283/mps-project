#
# Created by David Seery on 2019-02-28.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime
from functools import partial
from typing import Optional

from celery import group, chain
from celery.exceptions import Ignore
from flask import current_app
from flask_mailman import EmailMessage
from sqlalchemy.exc import SQLAlchemyError

from .shared.utils import report_info, report_error, attach_asset_to_email_msg
from ..database import db
from ..models import (
    SubmissionPeriodRecord,
    SubmissionRecord,
    ProjectClassConfig,
    ProjectClass,
    SubmissionRole,
    User,
    SubmittingStudent,
    StudentData,
    EmailLog,
    GeneratedAsset,
    FeedbackReport,
    EmailTemplate,
)
from ..shared.asset_tools import AssetCloudAdapter
from ..task_queue import register_task


def register_push_feedback_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def push_period(self, period_id, user_id, cc_convenor, test_email):
        try:
            period: SubmissionPeriodRecord = db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            self.update_state("FAILURE", meta={"msg": "Could not load database records"})
            print("!! push_period: ignored because cannot load SubmissionPeriodRecord")
            raise Ignore()

        # submitters is set of ids for SubmissionRecord instances
        submitters = set()

        # supervisors is set of ids for User instances
        supervisors = set()

        # markers is set of ids for User instances
        markers = set()

        for record in period.submissions:
            record: SubmissionRecord

            if record.has_feedback_to_push:
                if not record.feedback_sent:
                    submitters.add(record.id)

                for role in record.roles:
                    role: SubmissionRole
                    if not role.feedback_sent:
                        if role.role in [SubmissionRole.ROLE_SUPERVISOR, SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR]:
                            supervisors.add(role.user_id)

                        if role.role in [SubmissionRole.ROLE_MARKER]:
                            markers.add(role.user_id)

        submitter_tasks = [push_student_feedback.s(rec_id, user_id, cc_convenor, test_email) for rec_id in submitters if rec_id is not None]
        supervisor_tasks = [
            push_role_feedback.s(
                supervisor_id,
                period_id,
                user_id,
                [SubmissionRole.ROLE_SUPERVISOR, SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR],
                "push_to_supervisor",
                "Feedback for supervision students",
                cc_convenor,
                test_email,
                "push_supervisor",
            )
            for supervisor_id in supervisors
            if supervisor_id is not None
        ]
        marker_tasks = [
            push_role_feedback.s(
                marker_id,
                period_id,
                user_id,
                [SubmissionRole.ROLE_MARKER],
                "push_to_marker",
                "Examiner feedback for project students",
                cc_convenor,
                test_email,
                "push_marker",
            )
            for marker_id in markers
            if marker_id is not None
        ]

        tasks = group(submitter_tasks + supervisor_tasks + marker_tasks) | notify_feedback_push.s(period_id, user_id)

        raise self.replace(tasks)

    # default max attachment size to 50 Mb
    MAX_ATTACHMENT_SIZE = 50 * 1024 * 1024

    def _attach_reports(record: SubmissionRecord, msg: EmailMessage):
        current_size = 0

        # track attached documents
        manifest = []

        if not record.feedback_generated:
            return manifest

        # bucket map must be loaded at execution time, because we don't know what configuration we will use
        # (e.g. could even vary by which container we are running in)
        buckets = current_app.config.get("OBJECT_STORAGE_BUCKETS")

        for report in record.feedback_reports:
            report: FeedbackReport
            asset: GeneratedAsset = report.asset
            object_store = buckets[asset.bucket]

            storage = AssetCloudAdapter(asset, object_store, audit_data=f"push_feedback.attach_reports")
            d = attach_asset_to_email_msg(msg, storage, current_size, filename=asset.target_name, max_attached_size=MAX_ATTACHMENT_SIZE,
                                          description="feedback report", endpoint="download_generated_asset")
            current_size += d.attached_size
            manifest.extend(d.manifest)

        return manifest

    @celery.task(bind=True, default_retry_delay=30)
    def push_student_feedback(self, record_id, user_id, cc_convenor, test_email):
        try:
            record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load database records"})
            return {"error": 1}

        period: SubmissionPeriodRecord = record.period
        config: ProjectClassConfig = period.config
        pclass: ProjectClass = config.project_class

        sub: SubmittingStudent = record.owner
        sd: StudentData = sub.student
        student: User = sd.user

        # do nothing if feedback has already been sent
        if record.feedback_sent:
            return {"ignored": 1, "source": f"push_student_feedback (student={student.name})"}

        send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]
        msg = EmailTemplate.apply_(
            template_type=EmailTemplate.PUSH_FEEDBACK_PUSH_TO_STUDENT,
            to=[test_email if test_email is not None else student.email],
            subject_kwargs={"proj": pclass.name, "name": period.display_name},
            body_kwargs={"sub": sub, "sd": sd, "student": student, "period": period, "pclass": pclass, "record": record},
            body_attachments={"attached_docs": partial(_attach_reports, record)},
        )

        if test_email is None and cc_convenor:
            msg.cc = [config.convenor_email]

        # register a new task in the database
        task_id = register_task(
            msg.subject, description="{proj}: Push {name} feedback to {r}".format(r=", ".join(msg.to), proj=pclass.name, name=period.display_name)
        )

        send_tasks = chain(
            send_log_email.s(task_id, msg),
            mark_submitter_feedback_sent.s(record_id, user_id, test_email),
        )

        return self.replace(send_tasks)

    @celery.task(bind=True, default_retry_delay=30)
    def push_role_feedback(self, person_id, period_id, user_id, target_roles, template_name, email_subject, cc_convenor, test_email, outcome_label):
        try:
            period: SubmissionPeriodRecord = db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            self.update_state("FAILURE", meta={"msg": "Could not load database records"})
            return {"error": 1}

        try:
            person: User = db.session.query(User).filter_by(id=person_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if person is None:
            self.update_state("FAILURE", meta={"msg": "Could not load database records"})
            return {"error": 1}

        # build list of submitters for which we need to send emails to this person
        submitters = []
        for record in period.submissions:
            record: SubmissionRecord
            for role in record.roles:
                role: SubmissionRole
                if not role.feedback_sent and role.user_id == person_id and role.role in target_roles:
                    submitters.append(record)

        if len(submitters) == 0:
            # no work to do
            return {"ignored": 1, "source": f"push_role_feedback (person={person_id})"}

        config: ProjectClassConfig = period.config
        pclass: ProjectClass = config.project_class

        _TEMPLATE_TYPE_MAP = {
            "push_to_supervisor": EmailTemplate.PUSH_FEEDBACK_PUSH_TO_SUPERVISOR,
            "push_to_marker": EmailTemplate.PUSH_FEEDBACK_PUSH_TO_MARKER,
        }
        email_template_type = _TEMPLATE_TYPE_MAP.get(template_name)
        if email_template_type is None:
            raise RuntimeError(f"push_role_feedback: unknown template_name '{template_name}'")

        send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]

        msg = EmailTemplate.apply_(
            template_type=email_template_type,
            to=[test_email if test_email is not None else person.email],
            subject_kwargs={"pclass_name": pclass.name, "period_name": period.display_name, "email_subject": email_subject},
            body_kwargs={"person": person, "submitters": submitters, "period": period, "pclass": pclass},
            body_attachments={f'submitter_{submitter.id}': partial(_attach_reports, submitter) for submitter in submitters},
        )

        if test_email is None and cc_convenor:
            msg.cc = [config.convenor_email]


        # register a new task in the database
        task_id = register_task(
            msg.subject, description="{proj}: Push {name} feedback to {r}".format(r=", ".join(msg.to), proj=pclass.name, name=period.display_name)
        )

        send_tasks = chain(
            send_log_email.s(task_id, msg),
            mark_role_feedback_sent.s(person_id, period_id, user_id, target_roles, test_email, outcome_label),
        )

        return self.replace(send_tasks)

    @celery.task(bind=True, default_retry_delay=5)
    def mark_submitter_feedback_sent(self, result_data, record_id, user_id, test_email):
        if "outcome" not in result_data:
            print(f"!! mark_submitter_feedback_sent: no outcome in result_data (result_data={result_data})")
            return {"error": 1}

        outcome = result_data["outcome"]
        if outcome in ["unknown", "failure"]:
            print(f"!! mark_submitter_feedback_sent: outcome was unknown or failure (result_data={result_data})")
            return {"error": 1}

        if outcome in ["no-store"]:
            print(f"!! mark_submitter_feedback_sent: outcome was marked no-store (result_data={result_data})")
            return {"push_submitter": 1}

        user: Optional[User] = None
        if user_id is not None:
            try:
                user = db.session.query(User).filter_by(id=user_id).first()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        if outcome != "success":
            report_error(
                f'Unexpected outcome "{outcome}" from send_log_email task (data={result_data})',
                "mark_submitter_feedback_sent",
                user,
            )

        if test_email is not None:
            print(f">> mark_submitter_feedback_sent: not marking as sent because test_email={test_email}")
            return {"push_submitter": 1}

        try:
            record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load database records"})
            print("!! mark_submitter_feedback_sent: Could not load SubmissionRecord")
            data = {"error": 1}
            if "key" in result_data:
                data = data | {"push_submitter": 1}
            return data

        if "key" in result_data:
            try:
                email: Optional[EmailLog] = db.session.query(EmailLog).filter_by(id=result_data["key"]).first()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

            # TODO: add to an email log for this SubmissionRecord

        record.feedback_sent = True
        record.feedback_push_id = user_id
        record.feedback_push_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return {"push_submitter": 1}

    @celery.task(bind=True, default_retry_delay=5)
    def mark_role_feedback_sent(self, result_data, person_id, period_id, user_id, target_roles, test_email, outcome_label):
        if "outcome" not in result_data:
            print(f"!! mark_role_feedback_sent: no outcome in result_data (result_data={result_data})")
            return {"error": 1}

        outcome = result_data["outcome"]
        if outcome in ["unknown", "failure"]:
            print(f"!! mark_role_feedback_sent: outcome was unknown or failure (result_data={result_data})")
            return {"error": 1}

        if outcome in ["no-store"]:
            print(f"!! mark_role_feedback_sent: outcome was no-store (result_data={result_data})")
            return {outcome_label: 1}

        try:
            person: User = db.session.query(User).filter_by(id=person_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if person is None:
            self.update_state("FAILURE", meta={"msg": "Could not load database records"})
            return {"error": 1}

        user: Optional[User] = None
        if user_id is not None:
            try:
                user = db.session.query(User).filter_by(id=user_id).first()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        if outcome != "success":
            report_error(
                f'Unexpected outcome "{outcome}" from send_log_email task (data={result_data})',
                "mark_role_feedback_sent",
                user,
            )

        if test_email is not None:
            print(f">> mark_role_feedback_sent: not marking as sent because test_email={test_email}")
            return {outcome_label: 1}

        try:
            period: SubmissionPeriodRecord = db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            self.update_state("FAILURE", meta={"msg": "Could not load database records"})
            print("!! mark_role_feedback_sent: Could not load SubmissionRecord")
            data = {"error": 1}
            if "key" in result_data:
                data = data | {outcome_label: 1}
            return data

        email: Optional[EmailLog] = None
        if "key" in result_data:
            try:
                email = db.session.query(EmailLog).filter_by(id=result_data["key"]).first()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        for record in period.submissions:
            record: SubmissionRecord
            for role in record.roles:
                role: SubmissionRole
                if not role.feedback_sent and role.user_id == person_id and role.role in target_roles:
                    role.feedback_sent = True
                    role.feedback_push_id = user_id
                    role.feedback_push_timestamp = datetime.now()

                    if email is not None:
                        role.email_log.append(email)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return {outcome_label: 1}

    @celery.task(bind=True, default_retry_delay=5)
    def notify_feedback_push(self, result_data, period_id, user_id):
        if user_id is None:
            return

        try:
            period = db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            self.update_state("FAILURE", meta={"msg": "Could not load database records"})
            print("!! notify_feedback_push: ignored because cannot load SubmissionPeriodRecord")
            raise Ignore()

        config: ProjectClassConfig = period.config

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state("FAILURE", meta={"msg": "Could not load User record from database"})
            print("!! notify_feedback_push: ignored because cannot load User")
            raise Ignore()

        # result data should be a list of dicts
        push_submitter = 0
        push_supervisor = 0
        push_marker = 0
        ignored = 0
        error = 0

        if result_data is not None:
            if isinstance(result_data, list):
                for result in result_data:
                    if isinstance(result, dict):
                        if "push_submitter" in result:
                            push_submitter += result["push_submitter"]
                        if "push_marker" in result:
                            push_marker += result["push_marker"]
                        if "push_supervisor" in result:
                            push_supervisor += result["push_supervisor"]
                        if "ignored" in result:
                            ignored += result["ignored"]
                            print(f'!! notify_feedback_push: notified that a push was ignored: "{result}"')
                        if "error" in result:
                            error += result["error"]
                    else:
                        raise RuntimeError("Expected individual group results to be dictionaries")
            else:
                raise RuntimeError("Expected record result data to be a list")

        report_info(
            f"Pushed feedback for {config.name} {period.display_name}: {push_submitter} submitter, {push_supervisor} supervisor, {push_marker} marker, {ignored} ignored, {error} errors",
            "notify_feedback_push",
            user,
        )
