#
# Created by David Seery on 2019-02-28.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime, timedelta
from typing import List, Optional

from celery import group
from celery.exceptions import Ignore
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    EmailTemplate,
    EmailWorkflow,
    EmailWorkflowItem,
    EmailWorkflowItemAttachment,
    FeedbackReport,
    GeneratedAsset,
    ProjectClass,
    ProjectClassConfig,
    StudentData,
    SubmissionPeriodRecord,
    SubmissionRecord,
    SubmissionRole,
    SubmittingStudent,
    User,
)
from ..models.emails import encode_email_payload
from ..shared.workflow_logging import log_db_commit
from .shared.utils import report_info


def register_push_feedback_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def push_period(self, period_id, user_id, cc_convenor, test_email):
        try:
            period: SubmissionPeriodRecord = (
                db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
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
                        if role.role in [
                            SubmissionRole.ROLE_SUPERVISOR,
                            SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
                        ]:
                            supervisors.add(role.user_id)

                        if role.role in [SubmissionRole.ROLE_MARKER]:
                            markers.add(role.user_id)

        submitter_tasks = [
            push_student_feedback.s(rec_id, user_id, cc_convenor, test_email)
            for rec_id in submitters
            if rec_id is not None
        ]
        supervisor_tasks = [
            push_role_feedback.s(
                supervisor_id,
                period_id,
                user_id,
                [
                    SubmissionRole.ROLE_SUPERVISOR,
                    SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
                ],
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

        tasks = group(
            submitter_tasks + supervisor_tasks + marker_tasks
        ) | notify_feedback_push.s(period_id, user_id)

        return self.replace(tasks)

    # default max attachment size to 50 Mb
    MAX_ATTACHMENT_SIZE = 50 * 1024 * 1024

    def _collect_feedback_attachments(
        record: SubmissionRecord,
    ) -> List[EmailWorkflowItemAttachment]:
        if not record.feedback_generated:
            return []

        attachments = []
        for report in record.feedback_reports:
            report: FeedbackReport
            asset: GeneratedAsset = report.asset
            attachments.append(
                EmailWorkflowItemAttachment.build_(
                    name=str(asset.target_name or asset.unique_name),
                    description="feedback report",
                    generated_asset=asset,
                )
            )
        return attachments

    @celery.task(bind=True, default_retry_delay=30)
    def push_student_feedback(self, record_id, user_id, cc_convenor, test_email):
        try:
            record: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            return {"error": 1}

        period: SubmissionPeriodRecord = record.period
        config: ProjectClassConfig = period.config
        pclass: ProjectClass = config.project_class

        sub: SubmittingStudent = record.owner
        sd: StudentData = sub.student
        student: User = sd.user

        # do nothing if feedback has already been sent
        if record.feedback_sent:
            return {
                "ignored": 1,
                "source": f"push_student_feedback (student={student.name})",
            }

        attachments = _collect_feedback_attachments(record)

        template = EmailTemplate.find_template_(
            EmailTemplate.PUSH_FEEDBACK_PUSH_TO_STUDENT, pclass=pclass
        )
        workflow = EmailWorkflow.build_(
            name=f"Push student feedback: {pclass.name} — {student.name}",
            template=template,
            defer=timedelta(minutes=15),
            pclasses=[pclass],
            max_attachment_size=MAX_ATTACHMENT_SIZE,
        )
        db.session.add(workflow)
        db.session.flush()

        recipient_list = [test_email if test_email is not None else student.email]
        if test_email is None and cc_convenor:
            recipient_list.append(config.convenor_email)

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload(
                {"proj": pclass.name, "name": period.display_name}
            ),
            body_payload=encode_email_payload(
                {
                    "sub": sub,
                    "sd": sd,
                    "student": student,
                    "period": period,
                    "pclass": pclass,
                    "record": record,
                }
            ),
            recipient_list=recipient_list,
            attachments=attachments,
        )
        item.workflow = workflow
        db.session.add(item)

        if test_email is None:
            record.feedback_sent = True
            record.feedback_push_id = user_id
            record.feedback_push_timestamp = datetime.now()

        try:
            log_db_commit(
                f"Queued feedback email to student {student.name} ({pclass.name}, {period.display_name}) and marked feedback as sent",
                user=user_id,
                project_classes=pclass,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return {"push_submitter": 1}

    @celery.task(bind=True, default_retry_delay=30)
    def push_role_feedback(
        self,
        person_id,
        period_id,
        user_id,
        target_roles,
        template_name,
        email_subject,
        cc_convenor,
        test_email,
        outcome_label,
    ):
        try:
            period: SubmissionPeriodRecord = (
                db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            return {"error": 1}

        try:
            person: User = db.session.query(User).filter_by(id=person_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if person is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            return {"error": 1}

        # build list of submitters for which we need to send emails to this person
        submitters = []
        for record in period.submissions:
            record: SubmissionRecord
            for role in record.roles:
                role: SubmissionRole
                if (
                    not role.feedback_sent
                    and role.user_id == person_id
                    and role.role in target_roles
                ):
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
            raise RuntimeError(
                f"push_role_feedback: unknown template_name '{template_name}'"
            )

        all_attachments = []
        for submitter in submitters:
            all_attachments.extend(_collect_feedback_attachments(submitter))

        template = EmailTemplate.find_template_(email_template_type, pclass=pclass)
        workflow = EmailWorkflow.build_(
            name=f"Push role feedback: {pclass.name} — {person.name}",
            template=template,
            defer=timedelta(minutes=15),
            pclasses=[pclass],
            max_attachment_size=MAX_ATTACHMENT_SIZE,
        )
        db.session.add(workflow)
        db.session.flush()

        recipient_list = [test_email if test_email is not None else person.email]
        if test_email is None and cc_convenor:
            recipient_list.append(config.convenor_email)

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload(
                {
                    "pclass_name": pclass.name,
                    "period_name": period.display_name,
                    "email_subject": email_subject,
                }
            ),
            body_payload=encode_email_payload(
                {
                    "person": person,
                    "submitters": submitters,
                    "period": period,
                    "pclass": pclass,
                }
            ),
            recipient_list=recipient_list,
            attachments=all_attachments,
        )
        item.workflow = workflow
        db.session.add(item)

        if test_email is None:
            for record in period.submissions:
                record: SubmissionRecord
                for role in record.roles:
                    role: SubmissionRole
                    if (
                        not role.feedback_sent
                        and role.user_id == person_id
                        and role.role in target_roles
                    ):
                        role.feedback_sent = True
                        role.feedback_push_id = user_id
                        role.feedback_push_timestamp = datetime.now()

        try:
            log_db_commit(
                f"Queued feedback email to {person.name} ({pclass.name}, {period.display_name}) covering "
                f"{len(submitters)} submitter(s) and marked roles as sent",
                user=user_id,
                project_classes=pclass,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return {outcome_label: 1}

    @celery.task(bind=True, default_retry_delay=5)
    def notify_feedback_push(self, result_data, period_id, user_id):
        if user_id is None:
            return

        try:
            period = (
                db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load database records"}
            )
            print(
                "!! notify_feedback_push: ignored because cannot load SubmissionPeriodRecord"
            )
            raise Ignore()

        config: ProjectClassConfig = period.config

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load User record from database"}
            )
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
                            print(
                                f'!! notify_feedback_push: notified that a push was ignored: "{result}"'
                            )
                        if "error" in result:
                            error += result["error"]
                    else:
                        raise RuntimeError(
                            "Expected individual group results to be dictionaries"
                        )
            else:
                raise RuntimeError("Expected record result data to be a list")

        report_info(
            f"Pushed feedback for {config.name} {period.display_name}: {push_submitter} submitter, {push_supervisor} supervisor, {push_marker} marker, {ignored} ignored, {error} errors",
            "notify_feedback_push",
            user,
        )
