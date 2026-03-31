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
from celery import chain, group
from dateutil import parser
from flask import current_app
from pathvalidate import sanitize_filename
from sqlalchemy.exc import SQLAlchemyError
from weasyprint import CSS, HTML
from weasyprint.text.fonts import FontConfiguration

from ..database import db
from ..models import (
    AssetLicense,
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
from ..shared.security import validate_nonce
from ..shared.workflow_logging import log_db_commit
from .shared.utils import report_error, report_info
from .thumbnails import dispatch_thumbnail_task

AssetDictionary = Dict[str, AssetCloudScratchContextManager]


_SUPERVISOR_ROLES = frozenset(
    {SubmissionRoleTypesMixin.ROLE_SUPERVISOR, SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR}
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
            workflow: MarkingWorkflow = db.session.query(MarkingWorkflow).filter_by(id=workflow_id).first()
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
                test_user: User = db.session.query(User).filter_by(id=test_user_id).first()
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

        email_group = group(
            dispatch_emails.s(sr_id, cc_convenor, max_attachment, test_email, deadline)
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
            event: MarkingEvent = db.session.query(MarkingEvent).filter_by(id=event_id).first()
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
                test_user: User = db.session.query(User).filter_by(id=test_user_id).first()
                if test_user is not None:
                    test_email = test_user.email
            except SQLAlchemyError:
                pass

        eligible_pairs = []  # (sr_id, deadline_str)
        for workflow in event.workflows:
            if workflow.template is None:
                continue
            deadline_str = workflow.effective_deadline.isoformat() if workflow.effective_deadline else None
            for sr in workflow.submitter_reports:
                if sr.workflow_state < SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE:
                    continue
                if any(not mr.distributed for mr in sr.marking_reports):
                    eligible_pairs.append((sr.id, deadline_str))

        if not eligible_pairs:
            return

        email_group = group(
            dispatch_emails.s(sr_id, cc_convenor, max_attachment, test_email, deadline_str)
            for sr_id, deadline_str in eligible_pairs
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

    def _collect_marking_attachments(
        record: SubmissionRecord,
        workflow: MarkingWorkflow,
        report_name: str,
    ) -> List[EmailWorkflowItemAttachment]:
        """
        Build the attachment list for a marking notification email.

        If workflow.requires_report is True and the record has a processed_report, the report
        is included as the first attachment. All documents explicitly assigned to the workflow
        via workflow.attachments are then appended unconditionally.
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

        # Add all explicitly assigned workflow-level attachments
        for pa in workflow.attachments:
            pa: PeriodAttachment
            attachments.append(
                EmailWorkflowItemAttachment.build_(
                    name=str(pa.attachment.target_name or pa.attachment.unique_name),
                    description=pa.description or "",
                    submitted_asset=pa.attachment,
                )
            )

        return attachments

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
            filename_path = Path(asset.target_name if hasattr(asset, "target_name") else asset.filename)
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
        print(f'-- preparing email to supervisor "{user.name}" for submitter "{student.user.name}"')

        attachments = _collect_marking_attachments(record, workflow, report_name)

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
            filename_path = Path(asset.target_name if hasattr(asset, "target_name") else asset.filename)
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
        print(f'-- preparing email to marker "{user.name}" for submitter "{student.user.name}"')

        attachments = _collect_marking_attachments(record, workflow, report_name)

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
    ):
        """
        Send marking notification emails for all undistributed MarkingReport instances
        belonging to a single SubmitterReport.
        """
        try:
            sr: SubmitterReport = db.session.query(SubmitterReport).filter_by(id=submitter_report_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if sr is None:
            msg = f"Could not load SubmitterReport id={submitter_report_id} from database"
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

        undistributed: List[MarkingReport] = [mr for mr in sr.marking_reports if not mr.distributed]
        if not undistributed:
            return {"sent": 0}

        # Create one EmailWorkflow for this batch
        email_wf = EmailWorkflow.build_(
            name=f"Marking notification: {workflow.name} — {student.user.name}",
            template=workflow.template,
            defer=timedelta(minutes=15),
            pclasses=[pclass],
            max_attachment_size=max_attachment,
        )
        db.session.add(email_wf)
        db.session.flush()

        sent = 0
        for mr in undistributed:
            role: SubmissionRole = mr.role
            is_supervisor = role.role in _SUPERVISOR_ROLES

            if is_supervisor:
                filtered_supervisors = [r for r in supervisors if r.id != role.id]
                item = _build_supervisor_item(
                    role, record, workflow, config, pclass, submitter, student,
                    period, deadline_date, filtered_supervisors, markers, test_email, cc_convenor,
                    marking_report_id=mr.id,
                )
            else:
                filtered_markers = [r for r in markers if r.id != role.id]
                item = _build_marker_item(
                    role, record, workflow, config, pclass, submitter, student,
                    period, deadline_date, supervisors, filtered_markers, test_email, cc_convenor,
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
            mr: MarkingReport = db.session.query(MarkingReport).filter_by(id=marking_report_id).first()
            email_log: EmailLog = db.session.query(EmailLog).filter_by(id=email_log_id).first()
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

        try:
            log_db_commit(
                f"Linked distribution email #{email_log_id} to MarkingReport #{marking_report_id}",
                endpoint=self.name,
            )
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
            mr: MarkingReport = db.session.query(MarkingReport).filter_by(id=marking_report_id).first()
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
                role, record, workflow, config, pclass, submitter, student,
                period, deadline_date, filtered_supervisors, markers, test_email, cc_convenor,
                marking_report_id=mr.id,
            )
        else:
            filtered_markers = [r for r in markers if r.id != role.id]
            item = _build_marker_item(
                role, record, workflow, config, pclass, submitter, student,
                period, deadline_date, supervisors, filtered_markers, test_email, cc_convenor,
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

    @celery.task(bind=True, default_retry_delay=30)
    def conflate_marks_for_period(self, period_id: int, convenor_id: Optional[int]):
        try:
            period: SubmissionPeriodRecord = (
                db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            msg = "Could not load SubmissionPeriodRecord from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        # set up a task group to perform conflation for each record associated with this period
        tasks = group(
            conflate_marks.s(record.id, convenor_id) for record in period.submissions
        ) | notify_period_conflation.s(period.id, convenor_id)

        return self.replace(tasks)

    def sanity_check_grade(
        role: SubmissionRole, person: User, student: User, convenor: Optional[User]
    ):
        fail = False

        label: str = role.role_as_string.capitalize()
        if role.grade < 0:
            fail = True
            report_error(
                f"{label} {person.name} for submitter {student.name} has recorded grade < 0. This submitter has been ignored.",
                "conflate_marks",
                convenor,
            )
        if role.grade > 100:
            fail = True
            report_error(
                f"{label} {person.name} for submitter {student.name} has recorded grade > 100. This submitter has been ignored.",
                "conflate_marks",
                convenor,
            )

        if role.weight is not None:
            if role.weight <= 0.0:
                fail = True
                report_error(
                    f"{label} {person.name} for submitter {student.name} has assigned weight < 0. This submitter has been ignored.",
                    "conflate_marks",
                    convenor,
                )
            if role.weight > 1.0:
                fail = True
                report_error(
                    f"{label} {person.name} for submitter {student.name} has assigned weight > 1. This submitter has been ignored.",
                    "conflate_marks",
                    convenor,
                )

        return fail

    @celery.task(bind=True, default_retry_delay=30)
    def conflate_marks(self, record_id: int, convenor_id: Optional[int]):
        try:
            record: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        convenor: Optional[User] = None
        if convenor_id is not None:
            try:
                convenor = db.session.query(User).filter_by(id=convenor_id).first()
            except SQLAlchemyError as e:
                convenor = None

        if record is None:
            self.update_state(
                "FAILURE", meta={"msg": "Could not load SubmissionRecord from database"}
            )
            return {"not_conflated": 1}

        # TODO: allow adjustable conflation rules
        sub: SubmittingStudent = record.owner
        sd: StudentData = sub.student
        student: User = sd.user

        fail: bool = False

        # conflate supervisor marks
        supervisor_marks = []
        for role in record.supervisor_roles:
            person: User = role.user
            if role.role == SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR:
                if not role.signed_off:
                    fail = True
                    report_info(
                        f"Warning: responsible supervisor {person.name} for submitter {student.name} has not approved. This submitter has been ignored.",
                        "conflate_marks",
                        convenor,
                    )

            if role.grade is not None:
                if role.signed_off:
                    fail = sanity_check_grade(role, person, student, convenor)
                    supervisor_marks.append(
                        {
                            "grade": float(role.grade),
                            "weight": float(role.weight)
                            if role.weight is not None
                            else 1.0,
                        }
                    )

                else:
                    report_info(
                        f"Warning: supervisor {person.name} for submitter {student.name} has a recorded grade, but it is not signed off. Marks for this student have been conflated, but this supervisor has been ignored.",
                        "conflate_marks",
                        convenor,
                    )
            else:
                if role.role != SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR:
                    report_info(
                        f"Warning: supervisor {person.name} for submitter {student.name} has not recorded a grade. Marks for this student have been conflated, but this supervisor has been ignored.",
                        "conflate_marks",
                        convenor,
                    )

        if fail:
            return {"not_conflated": 1}

        sum_weight = sum(m["weight"] for m in supervisor_marks)
        if not 1 - 1e-5 < sum_weight < 1 + 1e-5:
            report_error(
                f"Supervisor weights for submitter {student.name} do not sum to 1.0 (weight total={sum_weight:.3f}. This submitter has been ignored.",
                "conflate_marks",
                convenor,
            )
            return {"not_conflated": 1}

        # conflate examiner/markers
        marker_marks = []
        for role in record.marker_roles:
            person: User = role.user
            if role.grade is not None:
                if role.signed_off:
                    fail = sanity_check_grade(role, person, student, convenor)
                    marker_marks.append(
                        {
                            "grade": float(role.grade),
                            "weight": float(role.weight)
                            if role.weight is not None
                            else 1.0,
                        }
                    )

                else:
                    report_info(
                        f"Warning: marker {person.name} for submitter {student.name} has a recorded grade, but it is not signed off. Marks for this student have been conflated, but this marker has been ignored.",
                        "conflate_marks",
                        convenor,
                    )
            else:
                report_info(
                    f"Warning: marker {person.name} for submitter {student.name} has not recorded a grade. Marks for this student have been conflated, but this supervisor has been ignored.",
                    "conflate_marks",
                    convenor,
                )

        if fail:
            return {"not_conflated": 1}

        sum_weight = sum(m["weight"] for m in marker_marks)
        if not 1 - 1e-5 < sum_weight < 1 + 1e-5:
            report_error(
                f"Marker weights for submitter {student.name} do not sum to 1.0 (weight total={sum_weight:.3f}. This submitter has been ignored.",
                "conflate_marks",
                convenor,
            )
            return {"not_conflated": 1}

        # round up from 0.45%
        record.supervision_grade = round(
            sum(m["weight"] * m["grade"] for m in supervisor_marks) + 0.05, 0
        )
        record.report_grade = round(
            sum(m["weight"] * m["grade"] for m in marker_marks) + 0.05, 0
        )

        record.grade_generated_id = convenor_id
        record.grade_generated_timestamp = datetime.now()

        config: ProjectClassConfig = sub.config
        print(
            f'>> conflate_marks: {config.abbreviation} submitted "{student.name}" was assigned supervision grade={record.supervision_grade:.1f}%, report grade={record.report_grade:.1f}%'
        )

        try:
            log_db_commit(
                f"Saved conflated marks for {student.name} ({config.abbreviation}): "
                f"supervision grade={record.supervision_grade:.1f}%, report grade={record.report_grade:.1f}%",
                user=convenor,
                student=sd,
                project_classes=config.project_class,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        return {"conflated": 1}

    @celery.task(bind=True, default_retry_delay=5)
    def notify_period_conflation(self, result_data, period_id, convenor_id):
        try:
            convenor: Optional[User] = (
                db.session.query(User).filter_by(id=convenor_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if convenor is None:
            msg = "Could not load convenor User record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        try:
            period: SubmissionPeriodRecord = (
                db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            msg = "Could not load period record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        # result data should be a list of lists
        marks_conflated = 0
        marks_not_conflated = 0

        if result_data is not None:
            if isinstance(result_data, list):
                for result in result_data:
                    if isinstance(result, dict):
                        if "conflated" in result:
                            marks_conflated += result["conflated"]
                        if "not_conflated" in result:
                            marks_not_conflated += result["not_conflated"]
                    else:
                        raise RuntimeError(
                            "Expected individual results to be dictionaries"
                        )
            else:
                raise RuntimeError("Expected result data to be a list")

        conflated_plural = "s"
        not_conflated_plural = "s"
        if marks_conflated == 1:
            conflated_plural = ""
        if marks_not_conflated == 1:
            not_conflated_plural = ""

        report_info(
            f"{period.display_name}: {marks_conflated} submitter{conflated_plural} conflated successfully, and {marks_not_conflated} submitter{not_conflated_plural} not conflated",
            "notify_period_conflation",
            convenor,
        )

        return {
            "total_conflated": marks_conflated,
            "total_ignored": marks_not_conflated,
        }

    @celery.task(bind=True, default_retry_delay=30)
    def generate_feedback_reports(
        self, recipe_id: int, period_id: int, convenor_id: Optional[int]
    ):
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

        try:
            period: SubmissionPeriodRecord = (
                db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            msg = "Could not load period record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        convenor: Optional[User] = None
        if convenor_id is not None:
            try:
                convenor = db.session.query(User).filter_by(id=convenor_id).first()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        config: ProjectClassConfig = period.config
        pclass: ProjectClass = config.project_class

        if pclass not in recipe.project_classes:
            msg = f'Can not apply feedback recipe "{recipe.label}" to {period.display_name} because it is not available for use on projects of class "{pclass.name}"'
            report_error(msg, "generate_feedback_reports", convenor)
            current_app.logger.error(msg)
            raise Exception(msg)

        tasks = group(
            generate_feedback_report.s(record.id, recipe_id, convenor_id)
            for record in period.submissions
        ) | finalize_feedback_reports.s(recipe_id, period_id, convenor_id)

        return self.replace(tasks)

    def markdown_filter(input):
        return markdown.markdown(input)

    @celery.task(bind=True, serializer="pickle", default_retry_delay=30)
    def generate_feedback_report(
        self, record_id: int, recipe_id: int, convenor_id: Optional[int]
    ):
        try:
            record: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            msg = "Could not load recipe record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        # if a feedback report has already been generated, do nothing
        if record.feedback_generated:
            return {"ignored": 1}

        # if this SubmissionRecord does not have feedback ready to go, do nothing
        if not record.has_feedback:
            return {"ignored": 1}

        sub: SubmittingStudent = record.owner
        sd: StudentData = sub.student
        student: User = sd.user
        period: SubmissionPeriodRecord = record.period
        config: ProjectClassConfig = period.config
        pclass: ProjectClass = config.project_class

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

        # Download all assets needed by the recipe.
        #
        # note, we have to do this each time we generate a report, rather than pre-downloading them, because we don't know
        # which container this task will run on (it might not be the container that downloaded them).
        # If we have to pay a cost for using API calls, as in a commercial cloud, then we might prefer a different solution
        # in which we download once, and then generate all the reports on the same container
        object_store = current_app.config.get("OBJECT_STORAGE_PROJECT")
        mgr = ScratchGroupManager(folder=current_app.config.get("SCRATCH_FOLDER"))

        template_asset: FeedbackAsset = recipe.template
        template_storage: AssetCloudAdapter = AssetCloudAdapter(
            template_asset.asset,
            object_store,
            audit_data="generate_feedback_reports.download_template",
        )
        with template_storage.download_to_scratch() as template_scratch:
            mgr.copy("template", template_scratch.path)

        for asset in recipe.asset_list:
            asset: FeedbackAsset
            asset_storage: AssetCloudAdapter = AssetCloudAdapter(
                asset.asset,
                object_store,
                audit_data="generate_feedback_reports.download_asset",
            )
            with asset_storage.download_to_scratch() as asset_scratch:
                mgr.copy(asset.label, asset_scratch.path)

        # expect to use fully qualified path names
        template_loader = jinja2.FileSystemLoader(searchpath="/")
        template_env = jinja2.Environment(loader=template_loader)

        # add markdown filter to template environment
        template_env.filters["markdown"] = markdown_filter

        # add path names for each of the assets
        for label, path in mgr.items():
            template_env.globals[label] = path

        # add variables for marking outcomes
        template_env.globals["supervisor_grade"] = record.supervision_grade
        template_env.globals["report_grade"] = record.report_grade

        supervisor_feedback = {}
        for role in record.supervisor_roles:
            role: SubmissionRole
            person: User = role.user
            if role.submitted_feedback:
                feedback = {}
                if role.positive_feedback and len(role.positive_feedback) > 0:
                    feedback["positive"] = role.positive_feedback
                if role.improvements_feedback and len(role.improvements_feedback) > 0:
                    feedback["improvements"] = role.improvements_feedback
                supervisor_feedback[person.name] = feedback

        marker_feedback = {}
        count = 1
        for role in record.marker_roles:
            role: SubmissionRole
            person: User = role.user
            if role.submitted_feedback:
                feedback = {}
                if role.positive_feedback and len(role.positive_feedback) > 0:
                    feedback["positive"] = role.positive_feedback
                if role.improvements_feedback and len(role.improvements_feedback) > 0:
                    feedback["improvements"] = role.improvements_feedback
                marker_feedback[count] = feedback
                count += 1

        template_env.globals["exam_number"] = sd.exam_number
        template_env.globals["student_last"] = student.last_name
        template_env.globals["student_first"] = student.first_name
        template_env.globals["student_fullname"] = student.name
        template_env.globals["student_email"] = student.email
        template_env.globals["period"] = period.display_name
        template_env.globals["pclass_name"] = pclass.name
        template_env.globals["pclass_abbreviation"] = pclass.abbreviation
        template_env.globals["year"] = config.year

        template_env.globals["supervisor_feedback"] = supervisor_feedback
        template_env.globals["marker_feedback"] = marker_feedback

        # read in template
        template = template_env.get_template(str(mgr.get("template")))

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
                pdf = HTML(filename=html_mgr.path, base_url=".").write_pdf(
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

                object_store = current_app.config.get("OBJECT_STORAGE_FEEDBACK")
                with open(pdf_mgr.path, "rb") as f:
                    with AssetUploadManager(
                        new_asset,
                        data=BytesIO(f.read()),
                        storage=object_store,
                        audit_data=f"generate_feedback_report ({config.abbreviation}, {student.name})",
                        length=pdf_mgr.path.stat().st_size,
                        mimetype="application/pdf",
                        validate_nonce=validate_nonce,
                    ) as upload_mgr:
                        pass

                try:
                    db.session.add(new_asset)
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

                try:
                    db.session.add(new_asset)
                    db.session.flush()
                except SQLAlchemyError as e:
                    db.session.rollback()
                    current_app.logger.exception(
                        "SQLAlchemyError exception", exc_info=e
                    )
                    raise self.retry()

                # add to the list of feedback reports for this record (there may be more than one)
                record.feedback_reports.append(new_report)

                record.feedback_generated = True
                record.feedback_generated_by = convenor
                record.feedback_generated_timestamp = datetime.now()

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

    @celery.task(bind=True, serializer="pickle", default_retry_delay=5)
    def finalize_feedback_reports(
        self, result_data, recipe_id: int, period_id: int, convenor_id: Optional[int]
    ):
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

        try:
            period: SubmissionPeriodRecord = (
                db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if period is None:
            msg = "Could not load period record from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        convenor: Optional[User] = None
        if convenor_id is not None:
            try:
                convenor = db.session.query(User).filter_by(id=convenor_id).first()
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

        # result data should be a list of lists
        reports_generated = 0
        reports_ignored = 0

        if result_data is not None:
            if isinstance(result_data, list):
                for result in result_data:
                    if isinstance(result, dict):
                        if "generated" in result:
                            reports_generated += result["generated"]
                        if "ignored" in result:
                            reports_ignored += result["ignored"]
                    else:
                        raise RuntimeError(
                            "Expected individual results to be dictionaries"
                        )
            else:
                raise RuntimeError("Expected result data to be a list")

        generated_plural = "s"
        ignored_plural = "s"
        ignored_were = "were"
        if reports_generated == 1:
            generated_plural = ""
        if reports_ignored == 1:
            ignored_plural = ""
        if reports_ignored == 1:
            ignored_were = "was"

        msg = f"{period.display_name}: Used feedback report recipe '{recipe.label}' to generate {reports_generated} feedback report{generated_plural}."
        if reports_ignored > 0:
            msg += (
                " "
                + f"{reports_ignored} submitter{ignored_plural} {ignored_were} ignored."
            )
        report_info(
            msg,
            "finalize_feedback_reports",
            convenor,
        )

        return {"total_generated": reports_generated, "total_ignored": reports_ignored}
