#
# Created by David Seery on 24/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import date, datetime, timedelta
from email.utils import parseaddr
from typing import Dict, Optional
from smtplib import (
    SMTPAuthenticationError,
    SMTPConnectError,
    SMTPDataError,
    SMTPException,
    SMTPHeloError,
    SMTPNotSupportedError,
    SMTPRecipientsRefused,
    SMTPResponseException,
    SMTPSenderRefused,
    SMTPServerDisconnected,
)

from flask import current_app
from flask_mailman import Mail
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    AssessorAttendanceData,
    ConfirmRequest,
    DescriptionComment,
    EmailLog,
    EmailNotification,
    EmailTemplate,
    EmailWorkflow,
    EmailWorkflowItem,
    FacultyData,
    LiveProject,
    MatchingAttempt,
    MatchingRecord,
    PresentationAssessment,
    Project,
    ProjectClass,
    ProjectClassConfig,
    ProjectDescription,
    ScheduleAttempt,
    ScheduleSlot,
    SelectingStudent,
    StudentData,
    SubmissionPeriodRecord,
    SubmissionRecord,
    SubmissionRole,
    SubmittingStudent,
    SupervisionEvent,
    User,
)
from ..models.emails import (
    _DATE_PREFIX,
    _DATETIME_PREFIX,
    _INTKEYS_MARKER,
    _OBJECT_PREFIX,
)

# ---------------------------------------------------------------------------
# Mapping from encoded model class name → SQLAlchemy model class.
# Extend this when new model types appear in email template kwargs.
# ---------------------------------------------------------------------------
_MODEL_REGISTRY: Dict[str, type] = {
    "AssessorAttendanceData": AssessorAttendanceData,
    "ConfirmRequest": ConfirmRequest,
    "DescriptionComment": DescriptionComment,
    "EmailNotification": EmailNotification,
    "FacultyData": FacultyData,
    "LiveProject": LiveProject,
    "MatchingAttempt": MatchingAttempt,
    "MatchingRecord": MatchingRecord,
    "PresentationAssessment": PresentationAssessment,
    "Project": Project,
    "ProjectClass": ProjectClass,
    "ProjectClassConfig": ProjectClassConfig,
    "ProjectDescription": ProjectDescription,
    "ScheduleAttempt": ScheduleAttempt,
    "ScheduleSlot": ScheduleSlot,
    "SelectingStudent": SelectingStudent,
    "StudentData": StudentData,
    "SubmissionPeriodRecord": SubmissionPeriodRecord,
    "SubmissionRecord": SubmissionRecord,
    "SubmissionRole": SubmissionRole,
    "SubmittingStudent": SubmittingStudent,
    "SupervisionEvent": SupervisionEvent,
    "User": User,
}


def _decode_payload_value(value):
    """
    Recursively decode a single value from an email payload dict.

    - Strings starting with '__object__<ClassName>:<pk>' are looked up in the DB.
    - Strings starting with '__date__' are parsed to a date.
    - Strings starting with '__datetime__' are parsed to a datetime.
    - Lists are decoded element-by-element.
    - Dicts marked with '__intkeys__' have their string keys converted back to ints.

    Raises LookupError if a required database object cannot be found.
    """
    if value is None:
        return None
    if isinstance(value, str):
        if value.startswith(_OBJECT_PREFIX):
            rest = value[len(_OBJECT_PREFIX):]
            model_name, pk_str = rest.rsplit(":", 1)
            pk = int(pk_str)
            model_cls = _MODEL_REGISTRY.get(model_name)
            if model_cls is None:
                raise LookupError(
                    f"_decode_payload_value: unknown model class '{model_name}'"
                )
            obj = db.session.query(model_cls).filter_by(id=pk).first()
            if obj is None:
                raise LookupError(
                    f"_decode_payload_value: {model_name} with id={pk} not found in database"
                )
            return obj
        if value.startswith(_DATETIME_PREFIX):
            return datetime.fromisoformat(value[len(_DATETIME_PREFIX):])
        if value.startswith(_DATE_PREFIX):
            return date.fromisoformat(value[len(_DATE_PREFIX):])
        return value
    if isinstance(value, list):
        return [_decode_payload_value(item) for item in value]
    if isinstance(value, dict):
        if value.get(_INTKEYS_MARKER):
            return {
                int(k): _decode_payload_value(v)
                for k, v in value.items()
                if k != _INTKEYS_MARKER
            }
        return {k: _decode_payload_value(v) for k, v in value.items()}
    return value


def _decode_email_payload(payload_dict: Optional[dict]) -> Optional[dict]:
    """
    Decode a full email payload dict, reconstructing all encoded values.
    Returns None when payload_dict is None.
    Raises LookupError for any '__object__' reference that cannot be resolved.
    """
    if payload_dict is None:
        return None
    return {k: _decode_payload_value(v) for k, v in payload_dict.items()}


# Public alias for use outside the tasks package (e.g., inspection/preview views).
decode_email_payload = _decode_email_payload


def register_email_workflow_tasks(celery, mail: Mail):
    @celery.task(bind=True, serializer="pickle")
    def poll_email_workflows(self):
        """
        Task 1: Scan for EmailWorkflow instances with outstanding sends and dispatch
        a send task for each eligible EmailWorkflowItem.
        """
        now = datetime.now()

        workflows = (
            db.session.query(EmailWorkflow)
            .filter(
                EmailWorkflow.completed.is_(False),
                EmailWorkflow.paused.is_(False),
                EmailWorkflow.send_time <= now,
            )
            .all()
        )

        print(
            f"poll_email_workflows: found {len(workflows)} active workflow(s) past their send_time"
        )

        initiated = 0
        workflows_checked = len(workflows)

        for workflow in workflows:
            pending_items = (
                db.session.query(EmailWorkflowItem)
                .filter(
                    EmailWorkflowItem.workflow_id == workflow.id,
                    EmailWorkflowItem.sent_timestamp.is_(None),
                    EmailWorkflowItem.paused.is_(False),
                    EmailWorkflowItem.send_in_progress_timestamp.is_(None),
                    EmailWorkflowItem.celery_send_in_progress_task_id.is_(None),
                )
                .all()
            )

            print(
                f"poll_email_workflows: workflow '{workflow.name}' (id={workflow.id}) "
                f"has {len(pending_items)} pending item(s)"
            )

            for item in pending_items:
                print(
                    f"poll_email_workflows: dispatching send task for "
                    f"EmailWorkflowItem id={item.id} in workflow '{workflow.name}' (id={workflow.id})"
                )
                send_workflow_item.apply_async(args=(item.id,))
                initiated += 1

        return {"workflows_checked": workflows_checked, "initiated": initiated}

    @celery.task(bind=True, retry_backoff=True, serializer="pickle")
    def send_workflow_item(self, item_id):
        """
        Task 2: Send the email for a single EmailWorkflowItem.
        Sets in-progress flags before attempting to send, then logs the result.
        On exception the task is retried; error fields are set to record the failure.
        """
        item = db.session.query(EmailWorkflowItem).filter_by(id=item_id).first()
        if item is None:
            print(
                f"send_workflow_item: EmailWorkflowItem id={item_id} not found; aborting"
            )
            return {"outcome": "not-found", "item_id": item_id}

        workflow = item.workflow
        if workflow is None:
            print(
                f"send_workflow_item: EmailWorkflowItem id={item_id} has no parent workflow; aborting"
            )
            return {"outcome": "no-workflow", "item_id": item_id}

        # Guard against duplicate sends: mark in-progress and commit immediately.
        item.send_attempts = (item.send_attempts or 0) + 1
        item.send_in_progress_timestamp = datetime.now()
        item.celery_send_in_progress_task_id = self.request.id

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "send_workflow_item: SQLAlchemyError setting in-progress flags",
                exc_info=e,
            )
            raise self.retry()

        print(
            f"send_workflow_item: beginning send attempt {item.send_attempts} "
            f"for EmailWorkflowItem id={item_id} (workflow='{workflow.name}', id={workflow.id})"
        )

        # Resolve common per-item send parameters.
        template = workflow.template
        to = item.recipient_addresses
        from_email = (
            item.from_email
        )  # None → apply_() / apply_raw_() uses MAIL_DEFAULT_SENDER
        reply_to = (
            item.reply_to_list
        )  # None → apply_() / apply_raw_() uses [MAIL_REPLY_TO]
        attachments = list(item.attachments) if item.attachments is not None else []
        max_attachment_size = workflow.max_attachment_size

        try:
            if item.subject_override is not None and item.body_override is not None:
                print(
                    f"send_workflow_item: using subject_override and body_override "
                    f"for EmailWorkflowItem id={item_id}"
                )
                msg = EmailTemplate.apply_raw_(
                    subject=item.subject_override,
                    html_body=item.body_override,
                    to=to,
                    from_email=from_email,
                    reply_to=reply_to,
                    attachments=attachments or None,
                    max_attachment_size=max_attachment_size,
                )
            else:
                print(
                    f"send_workflow_item: rendering from template type={template.type} "
                    f"for EmailWorkflowItem id={item_id}"
                )
                # Decode stored payloads, resolving any '__object__' DB references.
                try:
                    subject_kwargs = _decode_email_payload(item.subject_payload_dict) or None
                    body_kwargs = _decode_email_payload(item.body_payload_dict) or None
                except LookupError as lookup_err:
                    current_app.logger.exception(
                        f"send_workflow_item: database lookup failed while decoding payload "
                        f"for EmailWorkflowItem id={item_id}",
                        exc_info=lookup_err,
                    )
                    item.error_condition = True
                    item.error_message = (
                        f"Payload decode error — database object not found: {lookup_err}"
                    )
                    item.send_in_progress_timestamp = None
                    item.celery_send_in_progress_task_id = None
                    try:
                        db.session.commit()
                    except SQLAlchemyError:
                        db.session.rollback()
                    return {
                        "outcome": "error",
                        "item_id": item_id,
                        "error": str(lookup_err),
                    }
                msg = EmailTemplate.apply_(
                    template_type=template.type,
                    to=to,
                    from_email=from_email,
                    reply_to=reply_to,
                    subject_kwargs=subject_kwargs,
                    body_kwargs=body_kwargs,
                    attachments=attachments or None,
                    max_attachment_size=max_attachment_size,
                )
        except Exception as e:
            current_app.logger.exception(
                f"send_workflow_item: exception building email for item id={item_id}",
                exc_info=e,
            )
            item.error_condition = True
            item.error_message = f"Failed to build email message: {e}"
            item.send_in_progress_timestamp = None
            item.celery_send_in_progress_task_id = None
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
            raise self.retry()

        # Send the email.
        try:
            if current_app.config.get("EMAIL_IS_LIVE", False):
                if hasattr(msg, "body") and msg.body is not None:
                    with mail.get_connection() as connection:
                        connection.send_messages([msg])
                else:
                    current_app.logger.error(
                        "send_workflow_item: ignoring attempt to send email with empty body"
                    )
                    with mail.get_connection(backend="console") as connection:
                        msg.connection = connection
                        msg.send()
            else:
                with mail.get_connection(backend="console") as connection:
                    msg.connection = connection
                    msg.send()

        except TimeoutError as e:
            current_app.logger.info(
                f"send_workflow_item: TimeoutError for item id={item_id}"
            )
            current_app.logger.exception("TimeoutError exception", exc_info=e)
            item.error_condition = True
            item.error_message = f"TimeoutError: {e}"
            item.send_in_progress_timestamp = None
            item.celery_send_in_progress_task_id = None
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
            raise self.retry()

        except (
            SMTPAuthenticationError,
            SMTPConnectError,
            SMTPDataError,
            SMTPException,
            SMTPNotSupportedError,
            SMTPHeloError,
            SMTPRecipientsRefused,
            SMTPResponseException,
            SMTPSenderRefused,
            SMTPServerDisconnected,
        ) as e:
            current_app.logger.info(
                f"send_workflow_item: SMTP exception for item id={item_id}"
            )
            current_app.logger.exception("SMTP exception", exc_info=e)
            item.error_condition = True
            item.error_message = f"{type(e).__name__}: {e}"
            item.send_in_progress_timestamp = None
            item.celery_send_in_progress_task_id = None
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
            raise self.retry()

        # Email sent successfully.  Record success and write to EmailLog.
        print(
            f"send_workflow_item: email sent successfully for EmailWorkflowItem id={item_id}"
        )

        now = datetime.now()
        item.sent_timestamp = now
        item.send_in_progress_timestamp = None
        item.celery_send_in_progress_task_id = None
        item.error_condition = False
        item.error_message = None

        # Build EmailLog record only when running on a live email platform.
        log = None
        if current_app.config.get("EMAIL_IS_LIVE", False):
            to_list = msg.recipients()

            html = None
            if hasattr(msg, "alternatives"):
                for content, mimetype in msg.alternatives:
                    if mimetype == "text/html":
                        html = content
                        break

            recipients = []
            for rcpt in to_list:
                pair = parseaddr(rcpt)
                user = db.session.query(User).filter_by(email=pair[1]).first()
                if user is not None:
                    recipients.append(user)

            log = EmailLog(
                recipients=recipients,
                send_date=now,
                subject=msg.subject,
                body=msg.body,
                html=html,
            )
            db.session.add(log)

        item.email_log = log

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                f"send_workflow_item: SQLAlchemyError persisting send result for item id={item_id}",
                exc_info=e,
            )
            raise self.retry()

        return {
            "outcome": "success",
            "item_id": item_id,
            "log_id": log.id if log is not None else None,
        }

    @celery.task(bind=True, serializer="pickle")
    def cleanup_workflow_sends(self):
        """
        Task 3: Periodic cleanup of stale in-progress send tasks.
        Revokes Celery tasks that have been running for more than 10 minutes (or have
        no timestamp) and clears the corresponding in-progress fields.
        """
        now = datetime.now()
        cutoff = now - timedelta(minutes=10)

        stuck_items = (
            db.session.query(EmailWorkflowItem)
            .filter(
                EmailWorkflowItem.celery_send_in_progress_task_id.is_not(None),
            )
            .all()
        )

        print(
            f"cleanup_workflow_sends: found {len(stuck_items)} item(s) with an in-progress task ID set"
        )

        revoked = 0
        cleaned = 0

        for item in stuck_items:
            task_id = item.celery_send_in_progress_task_id

            if item.send_in_progress_timestamp is not None:
                # Only act if the task has been running long enough to be considered stuck.
                if item.send_in_progress_timestamp > cutoff:
                    # Task is still within the grace period; leave it alone.
                    continue

                print(
                    f"cleanup_workflow_sends: EmailWorkflowItem id={item.id} "
                    f"has been in progress since {item.send_in_progress_timestamp} "
                    f"(> 10 minutes); revoking task {task_id}"
                )
                result = celery.AsyncResult(task_id)
                if result.state in ("PENDING", "STARTED", "RETRY"):
                    celery.control.revoke(task_id, terminate=True)
                    print(f"cleanup_workflow_sends: revoked task {task_id}")
                    revoked += 1

                item.celery_send_in_progress_task_id = None
                item.send_in_progress_timestamp = None
                if not item.error_condition:
                    item.error_condition = True
                if not item.error_message:
                    item.error_message = f"Celery send task {task_id} was killed after exceeding the 10-minute timeout"
                cleaned += 1

            else:
                # No timestamp means the in-progress state is inconsistent; revoke immediately.
                print(
                    f"cleanup_workflow_sends: EmailWorkflowItem id={item.id} "
                    f"has task ID {task_id} but no send_in_progress_timestamp; revoking immediately"
                )
                result = celery.AsyncResult(task_id)
                if result.state in ("PENDING", "STARTED", "RETRY"):
                    celery.control.revoke(task_id, terminate=True)
                    print(f"cleanup_workflow_sends: revoked task {task_id}")
                    revoked += 1

                item.celery_send_in_progress_task_id = None
                if not item.error_condition:
                    item.error_condition = True
                if not item.error_message:
                    item.error_message = f"Celery send task {task_id} was found with no timestamp and was killed"
                cleaned += 1

        if cleaned > 0:
            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception(
                    "cleanup_workflow_sends: SQLAlchemyError committing cleanup changes",
                    exc_info=e,
                )
                raise self.retry()

        print(
            f"cleanup_workflow_sends: cleaned {cleaned} item(s), revoked {revoked} task(s)"
        )
        return {"cleaned": cleaned, "revoked": revoked}
