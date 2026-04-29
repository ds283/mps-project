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
from flask import current_app
from pathvalidate import sanitize_filename
from sqlalchemy.exc import SQLAlchemyError
from weasyprint import CSS, HTML
from weasyprint.text.fonts import FontConfiguration

from ..database import db
from ..models import (
    AssetLicense,
    ConflationReport,
    EmailLog,
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
from ..models.markingevent import SubmitterReportWorkflowStates
from ..models.submissions import SubmissionRoleTypesMixin
from ..shared.asset_tools import (
    AssetCloudAdapter,
    AssetCloudScratchContextManager,
    AssetUploadManager,
)
from ..shared.scratch import ScratchFileManager, ScratchGroupManager
from ..shared.workflow_logging import log_db_commit
from .shared.utils import report_info
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
    if workflow.requires_report and record.processed_report is not None:
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

        if workflow.template is None:
            current_app.logger.warning(
                f"send_marking_emails: MarkingWorkflow id={workflow_id} has no email template assigned; skipping"
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

        # Resolve deadline: use passed value, then workflow effective_deadline, then today
        if deadline is None and workflow.effective_deadline is not None:
            deadline = workflow.effective_deadline.isoformat()

        # Find SubmitterReports that are READY_TO_DISTRIBUTE (or later) with undistributed MarkingReports
        eligible_ids = []
        for sr in workflow.submitter_reports:
            if sr.workflow_state < SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE:
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

        pclass: ProjectClass = workflow.event.pclass
        email_wf = EmailWorkflow.build_(
            name=f"Marking notification: {workflow.name}",
            template=workflow.template,
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
        for workflow in event.workflows:
            if workflow.template is None:
                continue
            deadline_str = (
                workflow.effective_deadline.isoformat()
                if workflow.effective_deadline
                else None
            )
            workflow_sr_ids = []
            for sr in workflow.submitter_reports:
                if (
                    sr.workflow_state
                    < SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE
                ):
                    continue
                if any(not mr.distributed for mr in sr.marking_reports):
                    workflow_sr_ids.append(sr.id)

            if not workflow_sr_ids:
                continue

            pclass: ProjectClass = workflow.event.pclass
            email_wf = EmailWorkflow.build_(
                name=f"Marking notification: {workflow.name}",
                template=workflow.template,
                defer=timedelta(minutes=15),
                pclasses=[pclass],
                max_attachment_size=max_attachment,
            )
            db.session.add(email_wf)
            db.session.flush()
            for sr_id in workflow_sr_ids:
                eligible_triples.append((sr_id, deadline_str, email_wf.id))

        if not eligible_triples:
            return

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

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
            if test_email is None:
                mr.distributed = True
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
        # Flush so the newly added association is visible to subsequent count() queries
        # within this transaction.
        db.session.flush()

        # Advance SubmitterReport to AWAITING_GRADING_REPORTS once all distributed
        # MarkingReports have had their notification emails actually sent.
        sr: SubmitterReport = mr.submitter_report
        transitioned = False
        if (
            sr is not None
            and sr.workflow_state == SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE
        ):
            distributed_mrs = [mr2 for mr2 in sr.marking_reports if mr2.distributed]
            if distributed_mrs and all(
                mr2.distribution_emails.count() > 0 for mr2 in distributed_mrs
            ):
                sr.workflow_state = (
                    SubmitterReportWorkflowStates.AWAITING_GRADING_REPORTS
                )
                transitioned = True

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

        email_wf = EmailWorkflow.build_(
            name=f"Marking notification (single): {workflow.name} — {student.user.name}",
            template=workflow.template,
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
        if test_email is None:
            mr.distributed = True

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
            reports = []
            for mr in sr.marking_reports:
                reports.append(
                    {
                        "name": mr.role.user.name if mr.role and mr.role.user else None,
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
        output = template.render()

        with ScratchFileManager(suffix=".html") as html_mgr:
            HTML_file = open(html_mgr.path, "w")
            HTML_file.write(output)
            HTML_file.close()

            with ScratchFileManager(suffix=".pdf") as pdf_mgr:
                font_config = FontConfiguration()
                sheet = CSS(
                    string="""
                            body {
                                font-family: Roboto;
                            }
                            """,
                    font_config=font_config,
                )
                HTML(filename=html_mgr.path, base_url=".").write_pdf(
                    pdf_mgr.path,
                    stylesheets=[
                        "https://fonts.googleapis.com/css2?family=Roboto:ital,wght@0,100..900;1,100..900&display=swap",
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
