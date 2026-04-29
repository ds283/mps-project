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
from ..models import ConflationReport, MarkingEventWorkflowStates, TaskRecord
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


def _build_target_roles(notify_supervisors: bool, notify_markers: bool, notify_moderators: bool) -> List[int]:
    """Return the list of SubmissionRole role-type integers to notify, based on form flags."""
    roles = []
    if notify_supervisors:
        roles.extend([SubmissionRole.ROLE_SUPERVISOR, SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR])
    if notify_markers:
        roles.append(SubmissionRole.ROLE_MARKER)
    if notify_moderators:
        roles.append(SubmissionRole.ROLE_MODERATOR)
    return roles


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
                "period": period,
                "pclass": pclass,
                "cr": cr,
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


def _build_faculty_email_items_for_cr(
    cr: ConflationReport,
    defer: timedelta,
    test_email: Optional[str],
    target_roles: List[int],
) -> List[EmailWorkflowItem]:
    """
    Build EmailWorkflowItem instances for each unique faculty member associated
    with the ConflationReport's SubmissionRecord via the specified roles.
    Registers a link_feedback_email_to_cr callback on each item.
    """
    record: SubmissionRecord = cr.submission_record
    period: SubmissionPeriodRecord = record.period
    config: ProjectClassConfig = period.config
    pclass: ProjectClass = config.project_class

    if not target_roles:
        return []

    _TEMPLATE_TYPE_MAP = {
        SubmissionRole.ROLE_SUPERVISOR: EmailTemplate.PUSH_FEEDBACK_PUSH_TO_SUPERVISOR,
        SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR: EmailTemplate.PUSH_FEEDBACK_PUSH_TO_SUPERVISOR,
        SubmissionRole.ROLE_MARKER: EmailTemplate.PUSH_FEEDBACK_PUSH_TO_MARKER,
        SubmissionRole.ROLE_MODERATOR: EmailTemplate.PUSH_FEEDBACK_PUSH_TO_MARKER,
    }

    sub: SubmittingStudent = record.owner
    sd: StudentData = sub.student
    student: User = sd.user

    # Collect unique faculty members in target roles for this record
    faculty_ids_seen = set()
    items = []
    for role in record.roles:
        role: SubmissionRole
        if role.role not in target_roles:
            continue
        if role.user_id in faculty_ids_seen:
            continue
        faculty_ids_seen.add(role.user_id)

        person: User = role.user
        if person is None:
            continue

        template_type = _TEMPLATE_TYPE_MAP.get(role.role)
        if template_type is None:
            continue

        template = EmailTemplate.find_template_(template_type, pclass=pclass)
        if template is None:
            continue

        attachments = _collect_cr_feedback_attachments(cr)

        recipient_list = [test_email if test_email else person.email]
        if not test_email:
            recipient_list.append(config.convenor_email)

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({"proj": pclass.name, "name": student.name}),
            body_payload=encode_email_payload(
                {
                    "person": person,
                    "sub": sub,
                    "sr": record,
                    "sd": sd,
                    "period": period,
                    "pclass": pclass,
                    "cr": cr,
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

        Sets cr.feedback_sent, records the push user and timestamp, and links the EmailLog
        record into cr.feedback_emails.  Also checks whether all ConflationReports for the
        parent MarkingEvent now have feedback sent, and if so advances the event to CLOSED.
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

        # Advance MarkingEvent to CLOSED if all CRs now have feedback sent (Task 4)
        event: MarkingEvent = cr.marking_event
        if event is not None and event.workflow_state == MarkingEventWorkflowStates.READY_TO_PUSH_FEEDBACK:
            all_crs = event.conflation_reports.all()
            if all_crs and all(c.feedback_sent for c in all_crs):
                event.workflow_state = MarkingEventWorkflowStates.CLOSED

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

        Creates ONE EmailWorkflow for all student emails and ONE for all faculty emails.
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
        config: ProjectClassConfig = event.period.config
        defer = timedelta(hours=delay_hours)
        target_roles = _build_target_roles(notify_supervisors, notify_markers, notify_moderators)

        unsent_crs = [cr for cr in event.conflation_reports.all() if not cr.feedback_sent]

        if not unsent_crs:
            if task_id is not None:
                progress_update(
                    task_id, TaskRecord.SUCCESS, 100,
                    "No unsent feedback — nothing to dispatch.",
                    autocommit=True,
                )
            return

        # ---- Build ONE student EmailWorkflow with one item per CR ----
        student_template = EmailTemplate.find_template_(
            EmailTemplate.PUSH_FEEDBACK_PUSH_TO_STUDENT, pclass=pclass
        )
        student_workflow = None
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

        # ---- Build ONE faculty EmailWorkflow, aggregating by faculty member ----
        if target_roles:
            # Determine a suitable faculty template (use SUPERVISOR as default for the workflow)
            faculty_template = EmailTemplate.find_template_(
                EmailTemplate.PUSH_FEEDBACK_PUSH_TO_SUPERVISOR, pclass=pclass
            )
            if faculty_template is None:
                faculty_template = EmailTemplate.find_template_(
                    EmailTemplate.PUSH_FEEDBACK_PUSH_TO_MARKER, pclass=pclass
                )

            if faculty_template is not None:
                faculty_workflow = EmailWorkflow.build_(
                    name=f"Push faculty feedback: {pclass.name} — {event.name}",
                    template=faculty_template,
                    defer=defer,
                    pclasses=[pclass],
                    max_attachment_size=MAX_ATTACHMENT_SIZE,
                    creator=user_id,
                )
                db.session.add(faculty_workflow)
                db.session.flush()

                for cr in unsent_crs:
                    faculty_items = _build_faculty_email_items_for_cr(cr, defer, test_email, target_roles)
                    for item in faculty_items:
                        item.workflow = faculty_workflow
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
