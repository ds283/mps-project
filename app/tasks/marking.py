#
# Created by David Seery on 20/12/2019.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

import jinja2
import markdown
from celery import group
from dateutil import parser
from flask import current_app, url_for
from pathvalidate import sanitize_filename
from sqlalchemy.exc import SQLAlchemyError
from weasyprint import CSS, HTML
from weasyprint.text.fonts import FontConfiguration

from ..database import db
from ..models import (
    AssetLicense,
    ConflationReport,
    EmailLog,
    EmailTemplate,
    EmailWorkflow,
    EmailWorkflowItem,
    EmailWorkflowItemAttachment,
    FeedbackAsset,
    FeedbackRecipe,
    FeedbackReport,
    GeneratedAsset,
    LiveProject,
    MarkingEvent,
    MarkingReport,
    MarkingWorkflow,
    PeriodAttachment,
    ProjectClass,
    ProjectClassConfig,
    StudentData,
    SubmissionPeriodRecord,
    SubmissionRecord,
    SubmissionRole,
    SubmitterReport,
    SubmittingStudent,
    User,
)
from ..models.emails import encode_email_payload
from ..models.markingevent import (
    _TERMINAL_STATES,
    MarkingEventWorkflowStates,
    MarkingReportDistributionStates,
    SubmitterReportWorkflowStates,
)
from ..models.submissions import SubmissionRoleTypesMixin
from ..shared.asset_tools import (
    AssetCloudAdapter,
    AssetCloudScratchContextManager,
    AssetUploadManager,
)
from ..shared.scratch import ScratchFileManager, ScratchGroupManager
from ..shared.workflow_logging import log_db_commit
from .shared.utils import report_error, report_info
from .thumbnails import dispatch_thumbnail_task

AssetDictionary = Dict[str, AssetCloudScratchContextManager]


def _collect_marking_attachments(
    record: SubmissionRecord,
    workflow: MarkingWorkflow,
    report_name: str,
    target_role: Optional[int] = None,
) -> List[EmailWorkflowItemAttachment]:
    """
    Build the attachment list for a marking notification email.

    If workflow.requires_report is True and the record has a processed_report, the report
    is included as the first attachment. Workflow-level PeriodAttachment instances are then
    appended, filtered by target_role if supplied.

    :param target_role: If set, only include attachments accessible to this role integer
        (from SubmissionRoleTypesMixin). Attachments with an empty role set are always
        included (unrestricted). Pass None to include all attachments regardless of role.
    """
    attachments = []

    # Optionally add the processed report
    if record.processed_report is not None:
        attachments.append(
            EmailWorkflowItemAttachment.build_(
                name=report_name,
                description="student's submitted report",
                generated_asset=record.processed_report,
            )
        )

    # Add workflow-level attachments, filtered by role where requested
    for pa in workflow.attachments:
        pa: PeriodAttachment
        if target_role is not None and not pa.has_role_access(target_role):
            continue
        attachments.append(
            EmailWorkflowItemAttachment.build_(
                name=str(pa.attachment.target_name or pa.attachment.unique_name),
                description=pa.description or "",
                submitted_asset=pa.attachment,
            )
        )

    return attachments


_SUPERVISOR_ROLES = frozenset(
    {
        SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
        SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
    }
)


def _resolve_workflow_template(workflow: MarkingWorkflow, pclass: ProjectClass):
    """Return the best-matching active EmailTemplate for this workflow+pclass, or None."""
    return workflow.resolve_email_template()


def _resolve_workflow_reminder_template(
    workflow: MarkingWorkflow, pclass: ProjectClass
):
    """Return the best-matching active reminder EmailTemplate for this workflow+pclass, or None."""
    if workflow.role == SubmissionRoleTypesMixin.ROLE_MARKER:
        template_type = EmailTemplate.MARKING_MARKER_REMINDER
    elif workflow.role in _SUPERVISOR_ROLES:
        template_type = EmailTemplate.MARKING_SUPERVISOR_REMINDER
    else:
        return None
    try:
        return EmailTemplate.find_template_(template_type, pclass=pclass)
    except RuntimeError:
        return None


def _try_advance_to_awaiting_grading(sr: SubmitterReport) -> bool:
    """Advance sr to AWAITING_GRADING_REPORTS if every MarkingReport is in a terminal
    distribution state (EMAIL_CONFIRMED or NOT_REQUIRED). Returns True if transitioned."""
    if (
        sr is None
        or sr.workflow_state != SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE
    ):
        return False
    mrs = list(sr.marking_reports)
    if not mrs:
        return False
    if all(mr.distribution_state in _TERMINAL_STATES for mr in mrs):
        sr.workflow_state = SubmitterReportWorkflowStates.AWAITING_GRADING_REPORTS
        return True
    return False


def register_marking_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def send_marking_emails(
        self,
        workflow_id: int,
        cc_convenor: bool,
        max_attachment: int,
        test_user_id: Optional[int],
        convenor_id: Optional[int],
        deadline: Optional[str] = None,
    ):
        """
        Dispatch marking notification emails for all undistributed MarkingReport instances
        in a single MarkingWorkflow.
        """
        try:
            workflow: MarkingWorkflow = (
                db.session.query(MarkingWorkflow).filter_by(id=workflow_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if workflow is None:
            msg = f"Could not load MarkingWorkflow id={workflow_id} from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        event: MarkingEvent = workflow.event
        pclass: ProjectClass = event.pclass

        if (
            test_user_id is None
            and event.workflow_state == MarkingEventWorkflowStates.WAITING
        ):
            convenor: Optional[User] = (
                db.session.query(User).filter_by(id=convenor_id).first()
                if convenor_id is not None
                else None
            )
            report_error(
                f'Cannot send marking emails: marking event "{event.name}" has not been opened yet.',
                "send_marking_emails",
                convenor,
            )
            return

        _blocking = {
            SubmitterReportWorkflowStates.NOT_READY,
            SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION,
            SubmitterReportWorkflowStates.NEEDS_MODERATOR_ASSIGNED,
            SubmitterReportWorkflowStates.DROPPED,
        }

        resolved_template = _resolve_workflow_template(workflow, pclass)
        if resolved_template is None:
            # No email needed for this workflow role (e.g. ROLE_PRESENTATION_ASSESSOR).
            # Mark all undistributed MRs as NOT_REQUIRED and attempt to advance each SR.
            advanced = 0
            for sr in workflow.submitter_reports:
                if sr.workflow_state in _blocking:
                    continue
                for mr in sr.marking_reports:
                    if not mr.distributed:
                        mr.distribution_state = (
                            MarkingReportDistributionStates.NOT_REQUIRED
                        )
                if _try_advance_to_awaiting_grading(sr):
                    advanced += 1
            try:
                log_db_commit(
                    f"send_marking_emails: set NOT_REQUIRED for workflow id={workflow_id}; "
                    f"advanced {advanced} SubmitterReport(s) to AWAITING_GRADING_REPORTS",
                    endpoint=self.name,
                )
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()
            return

        # Resolve test email address from user id
        test_email: Optional[str] = None
        if test_user_id is not None:
            try:
                test_user: User = (
                    db.session.query(User).filter_by(id=test_user_id).first()
                )
                if test_user is not None:
                    test_email = test_user.email
            except SQLAlchemyError:
                pass

        # Resolve deadline: use passed value, then workflow effective_deadline, then today
        if deadline is None and workflow.effective_deadline is not None:
            deadline = workflow.effective_deadline.isoformat()

        # Find SubmitterReports that are READY_TO_DISTRIBUTE (or later) with undistributed MarkingReports
        eligible_ids = []
        for sr in workflow.submitter_reports:
            if sr.workflow_state in _blocking:
                continue
            if any(not mr.distributed for mr in sr.marking_reports):
                eligible_ids.append(sr.id)

        if not eligible_ids:
            return

        print(
            f"-- send_marking_emails: workflow={workflow.name!r}, "
            f"{len(eligible_ids)} submitter report(s) to notify"
        )
        if test_email is not None:
            print(f"-- working in test mode: emails being sent to sink={test_email}")

        email_wf = EmailWorkflow.build_(
            name=f"Marking notification: {workflow.name}",
            template=resolved_template,
            defer=timedelta(minutes=15),
            pclasses=[pclass],
            max_attachment_size=max_attachment,
        )
        db.session.add(email_wf)
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        email_group = group(
            dispatch_emails.s(
                sr_id, cc_convenor, max_attachment, test_email, deadline, email_wf.id
            )
            for sr_id in eligible_ids
        ) | notify_dispatch.s(convenor_id)

        return self.replace(email_group)

    @celery.task(bind=True, default_retry_delay=30)
    def send_marking_event_emails(
        self,
        event_id: int,
        cc_convenor: bool,
        max_attachment: int,
        test_user_id: Optional[int],
        convenor_id: Optional[int],
    ):
        """
        Dispatch marking notification emails for all workflows in a MarkingEvent that
        have undistributed reports and an assigned template.
        """
        try:
            event: MarkingEvent = (
                db.session.query(MarkingEvent).filter_by(id=event_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if event is None:
            msg = f"Could not load MarkingEvent id={event_id} from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        if (
            test_user_id is None
            and event.workflow_state == MarkingEventWorkflowStates.WAITING
        ):
            convenor: Optional[User] = (
                db.session.query(User).filter_by(id=convenor_id).first()
                if convenor_id is not None
                else None
            )
            report_error(
                f'Cannot send marking emails: marking event "{event.name}" has not been opened yet.',
                "send_marking_event_emails",
                convenor,
            )
            return

        # Resolve test email address from user id
        test_email: Optional[str] = None
        if test_user_id is not None:
            try:
                test_user: User = (
                    db.session.query(User).filter_by(id=test_user_id).first()
                )
                if test_user is not None:
                    test_email = test_user.email
            except SQLAlchemyError:
                pass

        eligible_triples = []  # (sr_id, deadline_str, email_workflow_id)
        not_required_changed = False
        _blocking = {
            SubmitterReportWorkflowStates.NOT_READY,
            SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION,
            SubmitterReportWorkflowStates.NEEDS_MODERATOR_ASSIGNED,
            SubmitterReportWorkflowStates.DROPPED,
        }
        for workflow in event.workflows:
            pclass: ProjectClass = workflow.event.pclass
            resolved_template = _resolve_workflow_template(workflow, pclass)
            if resolved_template is None:
                # No email needed for this workflow role. Mark undistributed MRs as NOT_REQUIRED
                # and attempt to advance each eligible SubmitterReport.
                for sr in workflow.submitter_reports:
                    if sr.workflow_state in _blocking:
                        continue
                    for mr in sr.marking_reports:
                        if not mr.distributed:
                            mr.distribution_state = (
                                MarkingReportDistributionStates.NOT_REQUIRED
                            )
                            not_required_changed = True
                    _try_advance_to_awaiting_grading(sr)
                continue
            deadline_str = (
                workflow.effective_deadline.isoformat()
                if workflow.effective_deadline
                else None
            )
            workflow_sr_ids = []
            for sr in workflow.submitter_reports:
                if sr.workflow_state in _blocking:
                    continue
                if any(not mr.distributed for mr in sr.marking_reports):
                    workflow_sr_ids.append(sr.id)

            if not workflow_sr_ids:
                continue

            email_wf = EmailWorkflow.build_(
                name=f"Marking notification: {workflow.name}",
                template=resolved_template,
                defer=timedelta(minutes=15),
                pclasses=[pclass],
                max_attachment_size=max_attachment,
            )
            db.session.add(email_wf)
            db.session.flush()
            for sr_id in workflow_sr_ids:
                eligible_triples.append((sr_id, deadline_str, email_wf.id))

        if not eligible_triples and not not_required_changed:
            return

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if not eligible_triples:
            return

        email_group = group(
            dispatch_emails.s(
                sr_id,
                cc_convenor,
                max_attachment,
                test_email,
                deadline_str,
                email_workflow_id,
            )
            for sr_id, deadline_str, email_workflow_id in eligible_triples
        ) | notify_dispatch.s(convenor_id)

        return self.replace(email_group)

    @celery.task(bind=True, default_retry_delay=5)
    def notify_dispatch(self, result_data, convenor_id):
        if convenor_id is None:
            return

        try:
            convenor: User = db.session.query(User).filter_by(id=convenor_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if convenor is None:
            msg = "Could not load User record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        total_sent = 0
        if result_data is not None:
            if isinstance(result_data, list):
                for item in result_data:
                    if isinstance(item, dict) and "sent" in item:
                        total_sent += item["sent"]
            elif isinstance(result_data, dict) and "sent" in result_data:
                total_sent += result_data["sent"]

        plural = "s" if total_sent != 1 else ""
        report_info(
            f"Dispatched {total_sent} marking notification{plural} to assessors",
            "notify_dispatch",
            convenor,
        )

    def _build_supervisor_item(
        role: SubmissionRole,
        record: SubmissionRecord,
        workflow: MarkingWorkflow,
        config: ProjectClassConfig,
        pclass: ProjectClass,
        submitter: SubmittingStudent,
        student: StudentData,
        period: SubmissionPeriodRecord,
        deadline: date,
        supervisors: List[SubmissionRole],
        markers: List[SubmissionRole],
        test_email: Optional[str],
        cc_convenor: bool,
        marking_report_id: Optional[int] = None,
    ) -> EmailWorkflowItem:
        asset = record.processed_report
        if asset is not None:
            filename_path = Path(
                asset.target_name if hasattr(asset, "target_name") else asset.filename
            )
            extension = filename_path.suffix.lower()
        else:
            extension = ".pdf"
        report_name = str(
            Path(
                "{year}_{abbv}_candidate_{number}".format(
                    year=config.year,
                    abbv=pclass.abbreviation,
                    number=student.exam_number,
                )
            ).with_suffix(extension)
        )

        user: User = role.user
        print(
            f'-- preparing email to supervisor "{user.name}" for submitter "{student.user.name}"'
        )

        attachments = _collect_marking_attachments(
            record, workflow, report_name, target_role=role.role
        )

        recipient = test_email if test_email is not None else user.email
        recipient_list = [recipient]
        if test_email is None and cc_convenor:
            recipient_list.append(config.convenor_email)

        callbacks = None
        if marking_report_id is not None and test_email is None:
            callbacks = [
                {
                    "task": "app.tasks.marking.link_distribution_email",
                    "args": [marking_report_id],
                    "kwargs": {},
                }
            ]

        marking_form_url = (
            url_for("faculty.marking_form", report_id=marking_report_id, _external=True)
            if marking_report_id is not None
            else None
        )

        return EmailWorkflowItem.build_(
            subject_payload=encode_email_payload(
                {
                    "abbv": pclass.abbreviation,
                    "stu": student.user.name,
                    "deadline": deadline.strftime("%a %d %b"),
                }
            ),
            body_payload=encode_email_payload(
                {
                    "role": role,
                    "config": config,
                    "pclass": pclass,
                    "period": period,
                    "markers": markers,
                    "supervisors": supervisors,
                    "submitter": submitter,
                    "project": record.project,
                    "student": student,
                    "record": record,
                    "deadline": deadline,
                    "marking_form_url": marking_form_url,
                }
            ),
            recipient_list=recipient_list,
            reply_to=[pclass.convenor_email],
            attachments=attachments,
            callbacks=callbacks,
        )

    def _build_marker_item(
        role: SubmissionRole,
        record: SubmissionRecord,
        workflow: MarkingWorkflow,
        config: ProjectClassConfig,
        pclass: ProjectClass,
        submitter: SubmittingStudent,
        student: StudentData,
        period: SubmissionPeriodRecord,
        deadline: date,
        supervisors: List[SubmissionRole],
        markers: List[SubmissionRole],
        test_email: Optional[str],
        cc_convenor: bool,
        marking_report_id: Optional[int] = None,
    ) -> EmailWorkflowItem:
        asset = record.processed_report
        if asset is not None:
            filename_path = Path(
                asset.target_name if hasattr(asset, "target_name") else asset.filename
            )
            extension = filename_path.suffix.lower()
        else:
            extension = ".pdf"
        report_name = str(
            Path(
                "{year}_{abbv}_candidate_{number}".format(
                    year=config.year,
                    abbv=pclass.abbreviation,
                    number=student.exam_number,
                )
            ).with_suffix(extension)
        )

        user: User = role.user
        print(
            f'-- preparing email to marker "{user.name}" for submitter "{student.user.name}"'
        )

        attachments = _collect_marking_attachments(
            record, workflow, report_name, target_role=role.role
        )

        recipient = test_email if test_email is not None else user.email
        recipient_list = [recipient]
        if test_email is None and cc_convenor:
            recipient_list.append(config.convenor_email)

        callbacks = None
        if marking_report_id is not None and test_email is None:
            callbacks = [
                {
                    "task": "app.tasks.marking.link_distribution_email",
                    "args": [marking_report_id],
                    "kwargs": {},
                }
            ]

        marking_form_url = (
            url_for("faculty.marking_form", report_id=marking_report_id, _external=True)
            if marking_report_id is not None
            else None
        )

        return EmailWorkflowItem.build_(
            subject_payload=encode_email_payload(
                {
                    "abbv": pclass.abbreviation,
                    "number": student.exam_number,
                    "deadline": deadline.strftime("%a %d %b"),
                }
            ),
            body_payload=encode_email_payload(
                {
                    "role": role,
                    "config": config,
                    "pclass": pclass,
                    "period": period,
                    "markers": markers,
                    "supervisors": supervisors,
                    "submitter": submitter,
                    "project": record.project,
                    "student": student,
                    "record": record,
                    "deadline": deadline,
                    "marking_form_url": marking_form_url,
                }
            ),
            recipient_list=recipient_list,
            reply_to=[pclass.convenor_email],
            attachments=attachments,
            callbacks=callbacks,
        )

    @celery.task(bind=True, default_retry_delay=30)
    def dispatch_emails(
        self,
        submitter_report_id: int,
        cc_convenor: bool,
        max_attachment: int,
        test_email: Optional[str],
        deadline: Optional[str],
        email_workflow_id: int,
    ):
        """
        Send marking notification emails for all undistributed MarkingReport instances
        belonging to a single SubmitterReport.
        """
        try:
            sr: SubmitterReport = (
                db.session.query(SubmitterReport)
                .filter_by(id=submitter_report_id)
                .first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if sr is None:
            msg = (
                f"Could not load SubmitterReport id={submitter_report_id} from database"
            )
            current_app.logger.error(msg)
            raise Exception(msg)

        record: SubmissionRecord = sr.record
        workflow: MarkingWorkflow = sr.workflow

        # Skip if no project assigned
        if record.project is None:
            return {"sent": 0}

        # Skip if report required but not yet processed
        if workflow.requires_report and record.processed_report is None:
            return {"sent": 0}

        period: SubmissionPeriodRecord = record.period
        config: ProjectClassConfig = period.config
        pclass: ProjectClass = config.project_class
        submitter: SubmittingStudent = record.owner
        student: StudentData = submitter.student

        # Resolve deadline
        deadline_date: date
        if deadline is not None:
            deadline_date = parser.parse(deadline).date()
        elif workflow.effective_deadline is not None:
            deadline_date = workflow.effective_deadline.date()
        else:
            deadline_date = date.today()

        supervisors: List[SubmissionRole] = record.supervisor_roles
        markers: List[SubmissionRole] = record.marker_roles

        undistributed: List[MarkingReport] = [
            mr for mr in sr.marking_reports if not mr.distributed
        ]
        if not undistributed:
            return {"sent": 0}

        try:
            email_wf: EmailWorkflow = (
                db.session.query(EmailWorkflow).filter_by(id=email_workflow_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if email_wf is None:
            msg = f"dispatch_emails: could not load EmailWorkflow id={email_workflow_id} from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        sent = 0
        for mr in undistributed:
            role: SubmissionRole = mr.role
            is_supervisor = role.role in _SUPERVISOR_ROLES

            if is_supervisor:
                filtered_supervisors = [r for r in supervisors if r.id != role.id]
                item = _build_supervisor_item(
                    role,
                    record,
                    workflow,
                    config,
                    pclass,
                    submitter,
                    student,
                    period,
                    deadline_date,
                    filtered_supervisors,
                    markers,
                    test_email,
                    cc_convenor,
                    marking_report_id=mr.id,
                )
            else:
                filtered_markers = [r for r in markers if r.id != role.id]
                item = _build_marker_item(
                    role,
                    record,
                    workflow,
                    config,
                    pclass,
                    submitter,
                    student,
                    period,
                    deadline_date,
                    supervisors,
                    filtered_markers,
                    test_email,
                    cc_convenor,
                    marking_report_id=mr.id,
                )

            item.workflow = email_wf
            db.session.add(item)
            db.session.flush()  # obtain item.id before commit
            if test_email is None:
                mr.distribution_state = MarkingReportDistributionStates.EMAIL_QUEUED
                mr.email_workflow_item_id = item.id
            sent += 1

        try:
            log_db_commit(
                f"Distributed {sent} marking notification(s) for {student.user.name} "
                f"({pclass.name}, workflow={workflow.name!r})",
                student=student,
                project_classes=pclass,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return {"sent": sent}

    @celery.task(bind=True, default_retry_delay=30)
    def link_distribution_email(self, email_log_id: int, marking_report_id: int):
        """
        Callback invoked after a distribution email is successfully sent.
        Links the newly created EmailLog record to the MarkingReport.distribution_emails collection.
        Follows the pattern established by mark_attendance_prompt_sent() in app/tasks/attendance.py.
        The email_log_id is prepended to args automatically by the EmailWorkflowItem callback mechanism.
        """
        try:
            mr: MarkingReport = (
                db.session.query(MarkingReport).filter_by(id=marking_report_id).first()
            )
            email_log: EmailLog = (
                db.session.query(EmailLog).filter_by(id=email_log_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if mr is None:
            msg = f"link_distribution_email: could not find MarkingReport #{marking_report_id}"
            current_app.logger.error(msg)
            return

        if email_log is None:
            msg = f"link_distribution_email: could not find EmailLog #{email_log_id}"
            current_app.logger.error(msg)
            return

        mr.distribution_emails.append(email_log)
        db.session.flush()

        # Mark as confirmed and release the in-flight FK
        mr.distribution_state = MarkingReportDistributionStates.EMAIL_CONFIRMED
        mr.email_workflow_item_id = None

        sr: SubmitterReport = mr.submitter_report
        transitioned = _try_advance_to_awaiting_grading(sr)

        commit_msg = f"Linked distribution email #{email_log_id} to MarkingReport #{marking_report_id}"
        if transitioned:
            commit_msg += (
                f"; advanced SubmitterReport #{sr.id} to AWAITING_GRADING_REPORTS"
            )

        try:
            log_db_commit(commit_msg, endpoint=self.name)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def link_reminder_email(self, email_log_id: int, marking_report_id: int):
        """
        Callback invoked after a reminder email is successfully sent.
        Appends the EmailLog to MarkingReport.distribution_emails for audit purposes.
        Does NOT modify distributed, report_submitted, or any signed_off_* field.
        The email_log_id is prepended to args automatically by the EmailWorkflowItem callback mechanism.
        """
        try:
            mr: MarkingReport = (
                db.session.query(MarkingReport).filter_by(id=marking_report_id).first()
            )
            email_log: EmailLog = (
                db.session.query(EmailLog).filter_by(id=email_log_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if mr is None:
            msg = f"link_reminder_email: could not find MarkingReport #{marking_report_id}"
            current_app.logger.error(msg)
            return

        if email_log is None:
            msg = f"link_reminder_email: could not find EmailLog #{email_log_id}"
            current_app.logger.error(msg)
            return

        mr.distribution_emails.append(email_log)

        try:
            log_db_commit(
                f"Linked reminder email #{email_log_id} to MarkingReport #{marking_report_id}",
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def send_marking_reminders(
        self,
        workflow_id: int,
        cc_convenor: bool,
        max_attachment: int,
        test_user_id: Optional[int],
        convenor_id: Optional[int],
        deadline: Optional[str] = None,
        sr_id: Optional[int] = None,
        mr_id: Optional[int] = None,
    ):
        """
        Dispatch reminder emails for a single MarkingWorkflow, targeting:
        - MarkingReport instances that have been distributed but not yet submitted, and
        - MarkingReport instances (SUPERVISOR role) whose parent SubmitterReport is in
          AWAITING_RESPONSIBLE_SUPERVISOR_SIGNOFF — emailing each pending responsible supervisor.

        Optional sr_id/mr_id narrow the scope to a single SubmitterReport or MarkingReport.

        A single EmailWorkflow wraps all generated EmailWorkflowItems. A callback on each item
        links the sent EmailLog to MarkingReport.distribution_emails for audit purposes, without
        modifying any workflow-state flags.
        """
        try:
            workflow: MarkingWorkflow = (
                db.session.query(MarkingWorkflow).filter_by(id=workflow_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if workflow is None:
            msg = f"send_marking_reminders: could not load MarkingWorkflow id={workflow_id}"
            current_app.logger.error(msg)
            raise Exception(msg)

        event: MarkingEvent = workflow.event
        pclass: ProjectClass = event.pclass

        if (
            test_user_id is None
            and event.workflow_state == MarkingEventWorkflowStates.WAITING
        ):
            convenor: Optional[User] = (
                db.session.query(User).filter_by(id=convenor_id).first()
                if convenor_id is not None
                else None
            )
            report_error(
                f'Cannot send marking reminders: marking event "{event.name}" has not been opened yet.',
                "send_marking_reminders",
                convenor,
            )
            return

        resolved_template = _resolve_workflow_reminder_template(workflow, pclass)
        if resolved_template is None:
            current_app.logger.warning(
                f"send_marking_reminders: no active reminder template for workflow id={workflow_id}; skipping"
            )
            return

        # Resolve test email address
        test_email: Optional[str] = None
        if test_user_id is not None:
            try:
                test_user: User = (
                    db.session.query(User).filter_by(id=test_user_id).first()
                )
                if test_user is not None:
                    test_email = test_user.email
            except SQLAlchemyError:
                pass

        # Resolve deadline
        if deadline is None and workflow.effective_deadline is not None:
            deadline = workflow.effective_deadline.isoformat()

        _blocking = {
            SubmitterReportWorkflowStates.NOT_READY,
            SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION,
            SubmitterReportWorkflowStates.NEEDS_MODERATOR_ASSIGNED,
            SubmitterReportWorkflowStates.DROPPED,
        }

        # Collect eligible (sr, mr, target_role, is_responsible_supervisor) tuples
        eligible = []
        for sr in workflow.submitter_reports:
            if sr_id is not None and sr.id != sr_id:
                continue
            if sr.workflow_state in _blocking:
                continue
            for mr in sr.marking_reports:
                if mr_id is not None and mr.id != mr_id:
                    continue
                if not mr.distributed:
                    continue
                if not mr.report_submitted:
                    eligible.append((sr, mr, mr.role, False))
                elif mr.role.role in _SUPERVISOR_ROLES and (
                    sr.workflow_state
                    == SubmitterReportWorkflowStates.AWAITING_RESPONSIBLE_SUPERVISOR_SIGNOFF
                ):
                    for resp_role in mr.responsible_supervisors:
                        eligible.append((sr, mr, resp_role, True))

        convenor: Optional[User] = None
        if convenor_id is not None:
            try:
                convenor = db.session.query(User).filter_by(id=convenor_id).first()
            except SQLAlchemyError:
                pass

        if not eligible:
            report_info(
                f'No reminder-eligible reports found for workflow "{workflow.name}"',
                "send_marking_reminders",
                convenor,
            )
            return

        print(
            f"-- send_marking_reminders: workflow={workflow.name!r}, "
            f"{len(eligible)} reminder(s) to dispatch"
        )
        if test_email is not None:
            print(f"-- working in test mode: emails being sent to sink={test_email}")

        email_wf = EmailWorkflow.build_(
            name=f"Marking reminder: {workflow.name}",
            template=resolved_template,
            defer=timedelta(minutes=15),
            pclasses=[pclass],
            max_attachment_size=max_attachment,
        )
        db.session.add(email_wf)
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        sent = 0
        for sr, mr, target_role, is_responsible_supervisor in eligible:
            record: SubmissionRecord = sr.record
            period: SubmissionPeriodRecord = record.period
            config: ProjectClassConfig = period.config
            submitter: SubmittingStudent = record.owner
            student: StudentData = submitter.student

            deadline_date: date
            if deadline is not None:
                deadline_date = parser.parse(deadline).date()
            elif workflow.effective_deadline is not None:
                deadline_date = workflow.effective_deadline.date()
            else:
                deadline_date = date.today()

            supervisors: List[SubmissionRole] = record.supervisor_roles
            markers: List[SubmissionRole] = record.marker_roles

            recipient = test_email if test_email is not None else target_role.user.email
            recipient_list = [recipient]
            if test_email is None and cc_convenor:
                recipient_list.append(config.convenor_email)

            # Responsible supervisors sign off rather than fill in a marking form
            if is_responsible_supervisor:
                marking_form_url = None
            else:
                marking_form_url = url_for(
                    "faculty.marking_form", report_id=mr.id, _external=True
                )

            callbacks = None
            if test_email is None:
                callbacks = [
                    {
                        "task": "app.tasks.marking.link_reminder_email",
                        "args": [mr.id],
                        "kwargs": {},
                    }
                ]

            is_supervisor_role = target_role.role in _SUPERVISOR_ROLES
            if is_supervisor_role:
                subject_payload = encode_email_payload(
                    {
                        "abbv": pclass.abbreviation,
                        "stu": student.user.name,
                        "deadline": deadline_date.strftime("%a %d %b"),
                    }
                )
            else:
                subject_payload = encode_email_payload(
                    {
                        "abbv": pclass.abbreviation,
                        "number": student.exam_number,
                        "deadline": deadline_date.strftime("%a %d %b"),
                    }
                )

            body_payload = encode_email_payload(
                {
                    "role": target_role,
                    "config": config,
                    "pclass": pclass,
                    "period": period,
                    "markers": markers,
                    "supervisors": supervisors,
                    "submitter": submitter,
                    "project": record.project,
                    "student": student,
                    "record": record,
                    "deadline": deadline_date,
                    "marking_form_url": marking_form_url,
                }
            )

            item = EmailWorkflowItem.build_(
                subject_payload=subject_payload,
                body_payload=body_payload,
                recipient_list=recipient_list,
                reply_to=[pclass.convenor_email],
                callbacks=callbacks,
            )
            item.workflow = email_wf
            db.session.add(item)
            sent += 1

        try:
            log_db_commit(
                f"Dispatched {sent} marking reminder(s) for workflow {workflow.name!r} "
                f"({pclass.name})",
                project_classes=pclass,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        plural = "s" if sent != 1 else ""
        report_info(
            f'Dispatched {sent} marking reminder{plural} for workflow "{workflow.name}"',
            "send_marking_reminders",
            convenor,
        )

    @celery.task(bind=True, default_retry_delay=30)
    def dispatch_single_email(
        self,
        marking_report_id: int,
        cc_convenor: bool,
        max_attachment: int,
        test_email: Optional[str],
        deadline: Optional[str],
        force: bool = False,
    ):
        """
        Send a marking notification email for a single MarkingReport.
        If force=True, send even if already distributed (re-send).
        """
        try:
            mr: MarkingReport = (
                db.session.query(MarkingReport).filter_by(id=marking_report_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if mr is None:
            msg = f"Could not load MarkingReport id={marking_report_id} from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        if mr.distributed and not force:
            return {"sent": 0}

        sr: SubmitterReport = mr.submitter_report
        record: SubmissionRecord = sr.record
        workflow: MarkingWorkflow = sr.workflow

        if record.project is None:
            return {"sent": 0}

        if workflow.requires_report and record.processed_report is None:
            return {"sent": 0}

        period: SubmissionPeriodRecord = record.period
        config: ProjectClassConfig = period.config
        pclass: ProjectClass = config.project_class
        submitter: SubmittingStudent = record.owner
        student: StudentData = submitter.student

        deadline_date: date
        if deadline is not None:
            deadline_date = parser.parse(deadline).date()
        elif workflow.effective_deadline is not None:
            deadline_date = workflow.effective_deadline.date()
        else:
            deadline_date = date.today()

        supervisors: List[SubmissionRole] = record.supervisor_roles
        markers: List[SubmissionRole] = record.marker_roles
        role: SubmissionRole = mr.role
        is_supervisor = role.role in _SUPERVISOR_ROLES

        resolved_template = _resolve_workflow_template(workflow, pclass)
        if resolved_template is None:
            # No email needed for this workflow role. Mark as NOT_REQUIRED and try to advance.
            if test_email is None:
                mr.distribution_state = MarkingReportDistributionStates.NOT_REQUIRED
                _try_advance_to_awaiting_grading(mr.submitter_report)
                try:
                    log_db_commit(
                        f"dispatch_single_email: set NOT_REQUIRED for MarkingReport #{mr.id}",
                        endpoint=self.name,
                    )
                except SQLAlchemyError as e:
                    db.session.rollback()
                    current_app.logger.exception(
                        "SQLAlchemyError exception", exc_info=e
                    )
                    raise self.retry()
            return {"sent": 0}

        email_wf = EmailWorkflow.build_(
            name=f"Marking notification (single): {workflow.name} — {student.user.name}",
            template=resolved_template,
            defer=timedelta(minutes=15),
            pclasses=[pclass],
            max_attachment_size=max_attachment,
        )
        db.session.add(email_wf)
        db.session.flush()

        if is_supervisor:
            filtered_supervisors = [r for r in supervisors if r.id != role.id]
            item = _build_supervisor_item(
                role,
                record,
                workflow,
                config,
                pclass,
                submitter,
                student,
                period,
                deadline_date,
                filtered_supervisors,
                markers,
                test_email,
                cc_convenor,
                marking_report_id=mr.id,
            )
        else:
            filtered_markers = [r for r in markers if r.id != role.id]
            item = _build_marker_item(
                role,
                record,
                workflow,
                config,
                pclass,
                submitter,
                student,
                period,
                deadline_date,
                supervisors,
                filtered_markers,
                test_email,
                cc_convenor,
                marking_report_id=mr.id,
            )

        item.workflow = email_wf
        db.session.add(item)
        db.session.flush()  # obtain item.id before commit
        if test_email is None:
            mr.distribution_state = MarkingReportDistributionStates.EMAIL_QUEUED
            mr.email_workflow_item_id = item.id

        try:
            log_db_commit(
                f"Dispatched single marking notification for {student.user.name} "
                f"({pclass.name}, workflow={workflow.name!r}, force={force})",
                student=student,
                project_classes=pclass,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return {"sent": 1}

    def markdown_filter(input):
        return markdown.markdown(input)

    @celery.task(bind=True, serializer="pickle", default_retry_delay=30)
    def generate_feedback_report(
        self, conflation_report_id: int, recipe_id: int, convenor_id: Optional[int]
    ):
        """
        Render a feedback PDF for a single student using a Jinja2/WeasyPrint recipe.

        TEMPLATE ENVIRONMENT
        ====================
        The following variables are injected into the Jinja2 template environment.

        ORM objects (full SQLAlchemy model instances):
          student_user  -- User
          sd            -- StudentData
          pclass        -- ProjectClass
          config        -- ProjectClassConfig
          period        -- SubmissionPeriodRecord
          event         -- MarkingEvent
          record        -- SubmissionRecord

        Dynamic asset labels:
          One variable per FeedbackAsset.label in the recipe, each containing
          the absolute filesystem path (str) to the downloaded scratch file.

        Filters:
          markdown  -- renders a Markdown string to HTML (wraps markdown.markdown())

        CONFLATION REPORT SCHEMA  (variable: conflation_report)
        ========================================================
        Dict[str, float] — flat mapping from grade target names to evaluated
        float values, e.g. {"report": 72.5, "supervisor": 68.0}.

        Sourced from ConflationReport.conflation_report_as_dict, which normalises
        both the current structured format {"targets": {...}, "metadata": {...}}
        and the legacy flat format {"target_name": value, ...} into the same flat
        dict.  Returns {} when no conflation data exists.

        WORKFLOW DATA SCHEMA  (variable: workflow_data)
        ================================================
        Dict[str, WorkflowEntry] keyed by MarkingWorkflow.key.  Workflows with no
        key, or with no matching SubmitterReport for this record, are omitted.
        A SubmitterReport in the DROPPED state appears with all-None grade fields
        and an empty reports list so the template can distinguish "dropped" from
        "not applicable".

          workflow_data = {
              "<workflow_key>": {
                  "grade": float | None,
                  "grade_generated_by": str | None,         # User.name
                  "grade_generated_timestamp": str | None,  # "YYYY/MM/DD HH:MM"
                  "reports": [
                      {
                          "name": str | None,               # assessor display name
                          "role": SubmissionRole,           # ORM object
                          "grade": float | None,            # percentage, 2 dp
                          "report": str | None,             # JSON-serialised marking form data:
                                                            #   {"fields": {key: bool|str|float, ...},
                                                            #    "validation_failures": [...]}  (optional key)
                          "feedback_positive": str | None,
                          "feedback_improvement": str | None,
                          "feedback_timestamp": str | None,  # "YYYY/MM/DD HH:MM"
                      },
                      ...
                  ],
              },
              ...
          }

        ABORT PROTOCOL
        ==============
        The template may raise any Exception to signal that it cannot produce a
        valid PDF from the available data (e.g. required grades are missing).
        The task catches the exception, sets cr.feedback_generation_failed = True,
        clears cr.feedback_celery_id, commits, and returns {"generated": 0}
        without retrying.  The exception is logged at WARNING level.

        MAINTENANCE NOTE FOR FUTURE AGENTS
        ===================================
        This docstring is the authoritative reference for the template contract.
        It must be kept in sync with the environment-building code below whenever:
          - a new variable is added to or removed from template_env.globals
          - the structure of conflation_report or workflow_data changes
          - the abort protocol changes
        """
        try:
            cr: ConflationReport = (
                db.session.query(ConflationReport)
                .filter_by(id=conflation_report_id)
                .first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if cr is None:
            msg = f"Could not load ConflationReport id={conflation_report_id} from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        # idempotency: if feedback reports already exist, skip
        if cr.feedback_reports.count() > 0:
            return {"ignored": 1}

        # record that generation is underway so the inspector can show a progress indicator
        cr.feedback_celery_id = self.request.id
        cr.feedback_generation_failed = False
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        try:
            recipe: FeedbackRecipe = (
                db.session.query(FeedbackRecipe).filter_by(id=recipe_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if recipe is None:
            msg = "Could not load recipe record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        convenor: Optional[User] = None
        if convenor_id is not None:
            try:
                convenor = db.session.query(User).filter_by(id=convenor_id).first()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        record: SubmissionRecord = cr.submission_record
        submitter: SubmittingStudent = record.owner
        sd: StudentData = submitter.student
        student: User = sd.user
        period: SubmissionPeriodRecord = record.period
        config: ProjectClassConfig = period.config
        pclass: ProjectClass = config.project_class
        event: MarkingEvent = cr.marking_event

        # Download supporting assets needed by the recipe.
        # We re-download each time because we don't know which worker will handle this task.
        object_store = current_app.config.get("OBJECT_STORAGE_PROJECT")
        mgr = ScratchGroupManager(folder=current_app.config.get("SCRATCH_FOLDER"))

        for asset in recipe.asset_list:
            asset: FeedbackAsset
            asset_storage: AssetCloudAdapter = AssetCloudAdapter(
                asset.asset,
                object_store,
                audit_data="generate_feedback_report.download_asset",
            )
            with asset_storage.download_to_scratch() as asset_scratch:
                mgr.copy(asset.label, asset_scratch.path)

        # Template body is stored in the database — no file download needed
        template_body: str = recipe.template.template_body
        template_env = jinja2.Environment(
            loader=jinja2.DictLoader({"template": template_body})
        )

        # add basic data
        template_env.globals["student_user"] = student
        template_env.globals["sd"] = sd
        template_env.globals["pclass"] = pclass
        template_env.globals["config"] = config
        template_env.globals["period"] = period
        template_env.globals["event"] = event
        template_env.globals["record"] = record

        # add markdown filter to template environment
        template_env.filters["markdown"] = markdown_filter

        # add path names for each downloaded supporting asset
        for label, path in mgr.items():
            template_env.globals[label] = path

        # build conflation_report context variable
        conflation_data = cr.conflation_report_as_dict

        # build workflow_data context variable, keyed by MarkingWorkflow.key
        workflow_data = {}
        for workflow in event.workflows:
            if workflow.key is None:
                continue
            sr: SubmitterReport = workflow.submitter_reports.filter_by(
                record_id=record.id
            ).first()
            if sr is None:
                continue
            if sr.workflow_state == SubmitterReportWorkflowStates.DROPPED:
                workflow_data[workflow.key] = {
                    "grade": None,
                    "grade_generated_by": None,
                    "grade_generated_timestamp": None,
                    "reports": [],
                }
                continue
            reports = []
            for mr in sr.marking_reports:
                reports.append(
                    {
                        "name": mr.role.user.name if mr.role and mr.role.user else None,
                        "role": mr.role,
                        "grade": float(mr.grade) if mr.grade is not None else None,
                        "report": mr.report,
                        "feedback_positive": mr.feedback_positive,
                        "feedback_improvement": mr.feedback_improvement,
                        "feedback_timestamp": mr.feedback_timestamp.strftime(
                            "%Y/%m/%d %H:%M"
                        )
                        if mr.feedback_timestamp
                        else None,
                    }
                )
            workflow_data[workflow.key] = {
                "grade": float(sr.grade) if sr.grade is not None else None,
                "grade_generated_by": sr.grade_generated_by.name
                if sr.grade_generated_by
                else None,
                "grade_generated_timestamp": sr.grade_generated_timestamp.strftime(
                    "%Y/%m/%d %H:%M"
                )
                if sr.grade_generated_timestamp
                else None,
                "reports": reports,
            }

        template_env.globals["conflation_report"] = conflation_data
        template_env.globals["workflow_data"] = workflow_data

        template = template_env.get_template("template")
        try:
            output = template.render()
        except Exception as e:
            current_app.logger.warning(
                f"generate_feedback_report: template raised exception for "
                f"ConflationReport #{conflation_report_id}: {e}"
            )
            cr.feedback_generation_failed = True
            cr.feedback_celery_id = None
            try:
                db.session.commit()
            except SQLAlchemyError as db_e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=db_e)
                raise self.retry()
            mgr.cleanup()
            return {"generated": 0}

        with ScratchFileManager(suffix=".html") as html_mgr:
            HTML_file = open(html_mgr.path, "w")
            HTML_file.write(output)
            HTML_file.close()

            with ScratchFileManager(suffix=".pdf") as pdf_mgr:
                font_config = FontConfiguration()
                sheet = CSS(
                    string="",  # no body rule needed; the template handles fonts
                    font_config=font_config,
                )
                HTML(filename=html_mgr.path, base_url=".").write_pdf(
                    pdf_mgr.path,
                    stylesheets=[
                        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
                        "&family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&display=swap",
                        sheet,
                    ],
                    font_config=font_config,
                )
                target_name = sanitize_filename(
                    f"Feedback-{config.year}-{config.abbreviation}-{student.last_name}.pdf"
                )
                license = (
                    db.session.query(AssetLicense)
                    .filter_by(abbreviation="Work")
                    .first()
                )

                new_asset = GeneratedAsset(
                    timestamp=datetime.now(),
                    expiry=None,
                    parent_asset_id=None,
                    target_name=target_name,
                    license=license,
                )
                db.session.add(new_asset)

                feedback_store = current_app.config.get("OBJECT_STORAGE_FEEDBACK")
                with open(pdf_mgr.path, "rb") as f:
                    with AssetUploadManager(
                        new_asset,
                        data=BytesIO(f.read()),
                        storage=feedback_store,
                        audit_data=f"generate_feedback_report ({config.abbreviation}, {student.name})",
                        length=pdf_mgr.path.stat().st_size,
                        mimetype="application/pdf",
                    ) as upload_mgr:
                        pass

                try:
                    db.session.flush()
                except SQLAlchemyError as e:
                    db.session.rollback()
                    current_app.logger.exception(
                        "SQLAlchemyError exception", exc_info=e
                    )
                    raise self.retry()

                dispatch_thumbnail_task(new_asset)

                new_report = FeedbackReport(
                    asset=new_asset,
                    generated_id=convenor_id,
                    timestamp=datetime.now(),
                )
                db.session.add(new_report)

                try:
                    db.session.flush()
                except SQLAlchemyError as e:
                    db.session.rollback()
                    current_app.logger.exception(
                        "SQLAlchemyError exception", exc_info=e
                    )
                    raise self.retry()

                # attach to the ConflationReport
                # it may also later be attached to the SubmissionRecord (for document manager) after pushing to the student
                cr.feedback_reports.append(new_report)
                cr.feedback_sent = False
                cr.feedback_push_id = None
                cr.feedback_push_timestamp = None
                # record which recipe was used and clear the in-progress marker
                cr.recipe = recipe.label
                cr.feedback_celery_id = None
                cr.feedback_generation_failed = False

                new_asset.grant_user(student)
                for role in record.supervisor_roles:
                    new_asset.grant_user(role.user)
                for role in record.marker_roles:
                    new_asset.grant_user(role.user)
                for role in record.moderator_roles:
                    new_asset.grant_user(role.user)

                if convenor is not None:
                    new_asset.grant_user(convenor)

                project: LiveProject = record.project
                if project is not None and project.owner is not None:
                    new_asset.grant_user(project.owner.user)

                try:
                    log_db_commit(
                        f"Saved generated feedback report PDF for {student.name} ({pclass.name}, {period.display_name})",
                        user=convenor,
                        student=sd,
                        project_classes=pclass,
                        endpoint=self.name,
                    )
                except SQLAlchemyError as e:
                    db.session.rollback()
                    current_app.logger.exception(
                        "SQLAlchemyError exception", exc_info=e
                    )
                    raise self.retry()

        # remove downloaded files from the scratch folder
        mgr.cleanup()

        return {"generated": 1}
