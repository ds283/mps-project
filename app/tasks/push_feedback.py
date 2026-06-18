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

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    EmailLog,
    EmailTemplate,
    EmailWorkflow,
    EmailWorkflowItem,
    EmailWorkflowItemAttachment,
    FeedbackReport,
    GeneratedAsset,
    MarkingEvent,
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
from ..models import ConflationReport, MarkingWorkflow, SubmitterReport, SubmitterReportWorkflowStates, TaskRecord
from ..shared.workflow_logging import log_db_commit
from ..task_queue import progress_update
from .shared.utils import report_info


# ---------------------------------------------------------------------------
# Module-level helpers — callable from route handlers and Celery tasks alike
# ---------------------------------------------------------------------------

# default max attachment size to 50 Mb
MAX_ATTACHMENT_SIZE = 50 * 1024 * 1024


def _collect_cr_feedback_attachments(cr: ConflationReport) -> List[EmailWorkflowItemAttachment]:
    """Build a list of EmailWorkflowItemAttachment objects from a ConflationReport's feedback_reports."""
    attachments = []
    for report in cr.feedback_reports.all():
        report: FeedbackReport
        asset: GeneratedAsset = report.asset
        if asset is None:
            continue
        attachments.append(
            EmailWorkflowItemAttachment.build_(
                name=str(asset.target_name or asset.unique_name),
                description="feedback report",
                generated_asset=asset,
            )
        )
    return attachments


def _build_student_email_item(
    cr: ConflationReport,
    user_id: int,
    defer: timedelta,
    test_email: Optional[str],
) -> Optional[EmailWorkflowItem]:
    """
    Build an EmailWorkflowItem for the student feedback email for a single ConflationReport.
    Returns None if no appropriate template is found.
    Registers a mark_feedback_sent callback on the item.
    """
    record: SubmissionRecord = cr.submission_record
    sub: SubmittingStudent = record.owner
    sd: StudentData = sub.student
    student: User = sd.user
    period: SubmissionPeriodRecord = record.period
    config: ProjectClassConfig = period.config
    pclass: ProjectClass = config.project_class

    attachments = _collect_cr_feedback_attachments(cr)
    if not attachments:
        return None

    template = EmailTemplate.find_template_(
        EmailTemplate.PUSH_FEEDBACK_PUSH_TO_STUDENT, pclass=pclass
    )
    if template is None:
        current_app.logger.warning(
            f"_build_student_email_item: no PUSH_FEEDBACK_PUSH_TO_STUDENT template for pclass {pclass.id}"
        )
        return None

    recipient_list = [test_email if test_email else student.email]
    if not test_email:
        recipient_list.append(config.convenor_email)

    item = EmailWorkflowItem.build_(
        subject_payload=encode_email_payload({"proj": pclass.name, "name": student.name}),
        body_payload=encode_email_payload(
            {
                "sub": sub,
                "sr": record,
                "sd": sd,
                "student": student,
                "period": period,
                "pclass": pclass,
                "cr": cr,
                "project": record.project,
            }
        ),
        recipient_list=recipient_list,
        attachments=attachments,
        callbacks=[
            {
                "task": "app.tasks.push_feedback.mark_feedback_sent",
                "args": [cr.id, user_id],
                "kwargs": {},
            }
        ],
    )
    return item


def _build_role_group_email_items_for_cr(
    cr: ConflationReport,
    defer: timedelta,
    test_email: Optional[str],
    role_types: List[int],
) -> List[EmailWorkflowItem]:
    """
    Build EmailWorkflowItem instances for each unique faculty member whose role type
    appears in role_types (e.g. [ROLE_SUPERVISOR, ROLE_RESPONSIBLE_SUPERVISOR]).

    The template is owned by the enclosing EmailWorkflow; no template lookup is done here.
    Registers a link_feedback_email_to_cr callback on each item.
    """
    if not role_types:
        return []

    record: SubmissionRecord = cr.submission_record
    period: SubmissionPeriodRecord = record.period
    config: ProjectClassConfig = period.config
    pclass: ProjectClass = config.project_class

    sub: SubmittingStudent = record.owner
    sd: StudentData = sub.student
    student: User = sd.user

    faculty_ids_seen = set()
    items = []
    for role in record.roles:
        role: SubmissionRole
        if role.role not in role_types:
            continue
        if role.user_id in faculty_ids_seen:
            continue
        faculty_ids_seen.add(role.user_id)

        person: User = role.user
        if person is None:
            continue

        attachments = _collect_cr_feedback_attachments(cr)
        if not attachments:
            continue

        recipient_list = [test_email if test_email else person.email]
        if not test_email:
            recipient_list.append(config.convenor_email)

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({"pclass": pclass.name, "period": period.name, "name": student.name}),
            body_payload=encode_email_payload(
                {
                    "person": person,
                    "sub": sub,
                    "sr": record,
                    "sd": sd,
                    "student": sd,
                    "period": period,
                    "pclass": pclass,
                    "cr": cr,
                    "project": record.project,
                    "role": role,
                }
            ),
            recipient_list=recipient_list,
            attachments=attachments,
            callbacks=[
                {
                    "task": "app.tasks.push_feedback.link_feedback_email_to_cr",
                    "args": [cr.id],
                    "kwargs": {},
                }
            ],
        )
        items.append(item)

    return items


def register_push_feedback_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def mark_feedback_sent(self, email_log_id: int, cr_id: int, user_id: int):
        """
        Callback fired by the EmailWorkflowItem machinery after a student feedback email is
        successfully sent (email_log_id is prepended by the workflow processor).

        Sets cr.feedback_sent, records the push user and timestamp, links the EmailLog record
        into cr.feedback_emails, and advances the student's SubmitterReport to FEEDBACK_AVAILABLE
        so they can view their feedback on the web platform. The MarkingEvent itself is not
        closed here; the convenor closes it explicitly via the inspector.
        """
        try:
            cr: ConflationReport = db.session.query(ConflationReport).filter_by(id=cr_id).first()
            email_log: EmailLog = db.session.query(EmailLog).filter_by(id=email_log_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if cr is None:
            current_app.logger.error(f"mark_feedback_sent: ConflationReport #{cr_id} not found")
            return

        if email_log is None:
            current_app.logger.error(f"mark_feedback_sent: EmailLog #{email_log_id} not found")
            return

        cr.feedback_sent = True
        cr.feedback_push_id = user_id
        cr.feedback_push_timestamp = datetime.now()
        cr.feedback_emails.append(email_log)

        # Mirror the FeedbackReport objects into SubmissionRecord.feedback_reports so that
        # the document manager can surface them to the student.
        record: SubmissionRecord = cr.submission_record
        if record is not None:
            existing_ids = {r.id for r in record.feedback_reports.all()}
            for report in cr.feedback_reports.all():
                if report.id not in existing_ids:
                    record.feedback_reports.append(report)

        # Advance the SubmitterReport for this student to FEEDBACK_AVAILABLE so the student
        # can view feedback on the web platform. The MarkingEvent itself remains open until
        # the convenor explicitly closes it (Canvas push may still be pending).
        event: MarkingEvent = cr.marking_event
        if event is not None and record is not None:
            sr = (
                record.submitter_reports.join(MarkingWorkflow, SubmitterReport.workflow_id == MarkingWorkflow.id)
                .filter(MarkingWorkflow.event_id == event.id)
                .first()
            )
            if sr is not None and sr.workflow_state == SubmitterReportWorkflowStates.COMPLETED:
                sr.workflow_state = SubmitterReportWorkflowStates.FEEDBACK_AVAILABLE

        try:
            log_db_commit(
                f"Marked feedback as sent for ConflationReport #{cr_id} "
                f"(EmailLog #{email_log_id}); user_id={user_id}",
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def link_feedback_email_to_cr(self, email_log_id: int, cr_id: int):
        """
        Callback fired after a faculty feedback email is successfully sent.
        Links the EmailLog record into cr.feedback_emails.
        """
        try:
            cr: ConflationReport = db.session.query(ConflationReport).filter_by(id=cr_id).first()
            email_log: EmailLog = db.session.query(EmailLog).filter_by(id=email_log_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if cr is None:
            current_app.logger.error(f"link_feedback_email_to_cr: ConflationReport #{cr_id} not found")
            return

        if email_log is None:
            current_app.logger.error(f"link_feedback_email_to_cr: EmailLog #{email_log_id} not found")
            return

        cr.feedback_emails.append(email_log)

        try:
            log_db_commit(
                f"Linked faculty feedback EmailLog #{email_log_id} to ConflationReport #{cr_id}",
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def push_marking_event_feedback_task(
        self,
        event_id: int,
        user_id: int,
        delay_hours: int,
        test_email: Optional[str],
        notify_supervisors: bool,
        notify_markers: bool,
        notify_moderators: bool,
        task_id=None,
    ):
        """
        Celery task to push feedback for all unsent ConflationReports in a MarkingEvent.

        Creates up to four EmailWorkflow instances — one per audience: students, supervisors,
        markers, and moderators. Each faculty workflow is only created when the corresponding
        notify_* flag is True and the appropriate EmailTemplate resolves for the project class.
        Each EmailWorkflowItem has the appropriate mark_feedback_sent / link_feedback_email_to_cr
        callback registered so per-CR state is updated after each email is dispatched.
        """
        try:
            event: MarkingEvent = db.session.query(MarkingEvent).filter_by(id=event_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if event is None:
            msg = f"push_marking_event_feedback_task: MarkingEvent #{event_id} not found"
            current_app.logger.error(msg)
            if task_id is not None:
                progress_update(task_id, TaskRecord.FAILURE, 100, msg, autocommit=True)
            return

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        pclass: ProjectClass = event.pclass
        defer = timedelta(hours=delay_hours)

        unsent_crs = [cr for cr in event.conflation_reports.all() if not cr.feedback_sent]

        if not unsent_crs:
            if task_id is not None:
                progress_update(
                    task_id, TaskRecord.SUCCESS, 100,
                    "No unsent feedback — nothing to dispatch.",
                    autocommit=True,
                )
            return

        # ---- Build student EmailWorkflow — one item per unsent CR ----
        student_template = EmailTemplate.find_template_(
            EmailTemplate.PUSH_FEEDBACK_PUSH_TO_STUDENT, pclass=pclass
        )
        if student_template is not None:
            student_workflow = EmailWorkflow.build_(
                name=f"Push student feedback: {pclass.name} — {event.name}",
                template=student_template,
                defer=defer,
                pclasses=[pclass],
                max_attachment_size=MAX_ATTACHMENT_SIZE,
                creator=user_id,
            )
            db.session.add(student_workflow)
            db.session.flush()

            for cr in unsent_crs:
                item = _build_student_email_item(cr, user_id, defer, test_email)
                if item is not None:
                    item.workflow = student_workflow
                    db.session.add(item)

        # ---- Build supervisor EmailWorkflow ----
        if notify_supervisors:
            supervisor_template = EmailTemplate.find_template_(
                EmailTemplate.PUSH_FEEDBACK_PUSH_TO_SUPERVISOR, pclass=pclass
            )
            if supervisor_template is not None:
                supervisor_workflow = EmailWorkflow.build_(
                    name=f"Push supervisor feedback: {pclass.name} — {event.name}",
                    template=supervisor_template,
                    defer=defer,
                    pclasses=[pclass],
                    max_attachment_size=MAX_ATTACHMENT_SIZE,
                    creator=user_id,
                )
                db.session.add(supervisor_workflow)
                db.session.flush()

                for cr in unsent_crs:
                    for item in _build_role_group_email_items_for_cr(
                        cr,
                        defer,
                        test_email,
                        [SubmissionRole.ROLE_SUPERVISOR, SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR],
                    ):
                        item.workflow = supervisor_workflow
                        db.session.add(item)

        # ---- Build marker EmailWorkflow ----
        if notify_markers:
            marker_template = EmailTemplate.find_template_(
                EmailTemplate.PUSH_FEEDBACK_PUSH_TO_MARKER, pclass=pclass
            )
            if marker_template is not None:
                marker_workflow = EmailWorkflow.build_(
                    name=f"Push marker feedback: {pclass.name} — {event.name}",
                    template=marker_template,
                    defer=defer,
                    pclasses=[pclass],
                    max_attachment_size=MAX_ATTACHMENT_SIZE,
                    creator=user_id,
                )
                db.session.add(marker_workflow)
                db.session.flush()

                for cr in unsent_crs:
                    for item in _build_role_group_email_items_for_cr(
                        cr, defer, test_email, [SubmissionRole.ROLE_MARKER]
                    ):
                        item.workflow = marker_workflow
                        db.session.add(item)

        # ---- Build moderator EmailWorkflow ----
        if notify_moderators:
            moderator_template = EmailTemplate.find_template_(
                EmailTemplate.PUSH_FEEDBACK_PUSH_TO_MARKER, pclass=pclass
            )
            if moderator_template is not None:
                moderator_workflow = EmailWorkflow.build_(
                    name=f"Push moderator feedback: {pclass.name} — {event.name}",
                    template=moderator_template,
                    defer=defer,
                    pclasses=[pclass],
                    max_attachment_size=MAX_ATTACHMENT_SIZE,
                    creator=user_id,
                )
                db.session.add(moderator_workflow)
                db.session.flush()

                for cr in unsent_crs:
                    for item in _build_role_group_email_items_for_cr(
                        cr, defer, test_email, [SubmissionRole.ROLE_MODERATOR]
                    ):
                        item.workflow = moderator_workflow
                        db.session.add(item)

        try:
            log_db_commit(
                f"Queued feedback push for MarkingEvent '{event.name}' ({pclass.name}) — "
                f"{len(unsent_crs)} unsent ConflationReport(s)",
                user=user_id,
                project_classes=pclass,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is not None:
            report_info(
                f"Queued feedback push for {pclass.name} — {event.name}: "
                f"{len(unsent_crs)} student email(s) dispatched.",
                self.name,
                user,
            )

        if task_id is not None:
            progress_update(
                task_id, TaskRecord.SUCCESS, 100,
                f"Queued feedback emails for {len(unsent_crs)} student(s).",
                autocommit=True,
            )
