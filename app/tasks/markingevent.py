#
# Created by David Seery on 30/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
import random
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    CrontabSchedule,
    DatabaseSchedulerEntry,
    EmailTemplate,
    EmailWorkflow,
    EmailWorkflowItem,
    MarkingReport,
    MarkingWorkflow,
    ModeratorReport,
    SubmissionRole,
    SubmitterReport,
)
from ..models.emails import encode_email_payload
from ..models.markingevent import SubmitterReportWorkflowStates
from ..models.submissions import SubmissionRecord, SubmissionRoleTypesMixin
from ..shared.workflow_logging import log_db_commit
from .marking import _collect_marking_attachments


def _next_9am() -> datetime:
    """Return a datetime for 9am on the day following the current time."""
    now = datetime.now()
    candidate = now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return candidate


def _emit_sign_off_emails(mr: MarkingReport, responsible_roles: list) -> None:
    """
    Generate a MARKING_NEEDS_SIGN_OFF EmailWorkflow for all responsible supervisors who must
    sign off a supervisor's MarkingReport.  A single EmailWorkflow encapsulates all items;
    sending is deferred by 1 hour so that late edits within the window are still possible.
    """
    if not responsible_roles:
        return

    workflow = mr.workflow
    pclass = workflow.event.pclass

    try:
        tmpl = EmailTemplate.find_template_(
            EmailTemplate.MARKING_NEEDS_SIGN_OFF, pclass=pclass
        )
    except Exception:
        tmpl = None

    if tmpl is None:
        current_app.logger.warning(
            f"MARKING_NEEDS_SIGN_OFF template not found for pclass {pclass.id}; "
            f"skipping sign-off emails for MarkingReport #{mr.id}"
        )
        return

    try:
        email_wf = EmailWorkflow.build_(
            name=f"Sign-off required: marking report #{mr.id}",
            template=tmpl,
            defer=timedelta(hours=1),
            pclasses=[pclass],
        )
        db.session.add(email_wf)
        db.session.flush()

        for role in responsible_roles:
            item = EmailWorkflowItem.build_(
                subject_payload=encode_email_payload({"student": mr.student}),
                body_payload=encode_email_payload(
                    {"report": mr, "workflow": workflow, "pclass": pclass}
                ),
                recipient_list=[role.user.email],
            )
            item.workflow = email_wf
            db.session.add(item)

    except Exception as e:
        current_app.logger.exception(
            f"Could not generate sign-off emails for MarkingReport #{mr.id}", exc_info=e
        )


def _emit_moderation_required_emails(sr: SubmitterReport) -> None:
    """
    Generate a MARKING_OUT_OF_TOLERANCE EmailWorkflow targeting all users in the
    workflow's notify_on_moderation_required collection. Deferred to 9am the next morning.
    """
    workflow = sr.workflow
    pclass = workflow.event.pclass
    notify_users = workflow.notify_on_moderation_required.all()

    if not notify_users:
        return

    try:
        tmpl = EmailTemplate.find_template_(
            EmailTemplate.MARKING_OUT_OF_TOLERANCE, pclass=pclass
        )
    except Exception:
        tmpl = None

    if tmpl is None:
        current_app.logger.warning(
            f"MARKING_OUT_OF_TOLERANCE template not found for pclass {pclass.id}; "
            f"skipping moderation emails for SubmitterReport #{sr.id}"
        )
        return

    try:
        email_wf = EmailWorkflow.build_(
            name=f"Moderation required: submitter report #{sr.id}",
            template=tmpl,
            send_time=_next_9am(),
            pclasses=[pclass],
        )
        db.session.add(email_wf)
        db.session.flush()

        for user in notify_users:
            item = EmailWorkflowItem.build_(
                subject_payload=encode_email_payload({"student": sr.student}),
                body_payload=encode_email_payload(
                    {"submitter_report": sr, "workflow": workflow, "pclass": pclass}
                ),
                recipient_list=[user.email],
            )
            item.workflow = email_wf
            db.session.add(item)

    except Exception as e:
        current_app.logger.exception(
            f"Could not generate moderation emails for SubmitterReport #{sr.id}", exc_info=e
        )


def _emit_moderator_assignment_email(sr: SubmitterReport, role: SubmissionRole) -> None:
    """Generate a MARKING_MODERATOR email to the newly assigned moderator."""
    from pathlib import Path

    workflow = sr.workflow
    pclass = workflow.event.pclass

    try:
        tmpl = EmailTemplate.find_template_(
            EmailTemplate.MARKING_MODERATOR, pclass=pclass
        )
    except Exception:
        tmpl = None

    if tmpl is None:
        current_app.logger.warning(
            f"MARKING_MODERATOR template not found for pclass {pclass.id}; "
            f"skipping moderator email for SubmitterReport #{sr.id}"
        )
        return

    try:
        record = sr.record
        student = sr.student
        config = pclass.most_recent_config

        asset = record.processed_report
        if asset is not None:
            ext = Path(asset.target_name if hasattr(asset, "target_name") else asset.filename).suffix.lower()
        else:
            ext = ".pdf"

        report_name = "{year}_{abbv}_candidate_{number}{ext}".format(
            year=config.year,
            abbv=pclass.abbreviation,
            number=student.exam_number,
            ext=ext,
        )

        attachments = _collect_marking_attachments(
            record, workflow, report_name,
            target_role=SubmissionRoleTypesMixin.ROLE_MODERATOR,
        )

        email_wf = EmailWorkflow.build_(
            name=f"Moderator assignment: submitter report #{sr.id}",
            template=tmpl,
            defer=timedelta(minutes=15),
            pclasses=[pclass],
        )
        db.session.add(email_wf)
        db.session.flush()

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({"student": sr.student}),
            body_payload=encode_email_payload(
                {"submitter_report": sr, "workflow": workflow, "pclass": pclass}
            ),
            recipient_list=[role.user.email],
            attachments=attachments,
        )
        item.workflow = email_wf
        db.session.add(item)

    except Exception as e:
        current_app.logger.exception(
            f"Could not generate moderator assignment email for SubmitterReport #{sr.id}",
            exc_info=e,
        )


def _assign_moderator(sr: SubmitterReport, role: SubmissionRole) -> None:
    """
    Create a ModeratorReport for the given ROLE_MODERATOR SubmissionRole, send the assignment
    email, and advance the SubmitterReport to AWAITING_MODERATOR_REPORT.
    """
    mod_report = ModeratorReport(
        role_id=role.id,
        submitter_report_id=sr.id,
        grade=None,
        report=None,
        report_submitted=False,
        submitted_timestamp=None,
        creator_id=None,
        creation_timestamp=datetime.now(),
    )
    db.session.add(mod_report)

    _emit_moderator_assignment_email(sr, role)
    sr.workflow_state = SubmitterReportWorkflowStates.AWAITING_MODERATOR_REPORT


def _check_tolerance_and_grade(sr: SubmitterReport, reports: list) -> None:
    """
    Compute the weighted average grade (or handle the out-of-tolerance case) and advance
    the SubmitterReport accordingly.
    """
    # Turnitin override: if an unresolved high-similarity score is present, the SR cannot
    # advance past REQUIRES_CONVENOR_INTERVENTION regardless of the marking-report state.
    if (
        sr.record.turnitin_score is not None
        and sr.record.turnitin_score >= 25
        and not sr.turnitin_resolved
    ):
        sr.workflow_state = SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION
        return

    scheme = sr.workflow.scheme

    if scheme is None or not scheme.uses_tolerance:
        # No tolerance check: compute weighted average grade and advance to READY_TO_SIGN_OFF
        total_weight = sum(float(r.weight) if r.weight is not None else 1.0 for r in reports)
        if total_weight == 0:
            total_weight = len(reports)
        sr.grade = sum(
            float(r.grade) * (float(r.weight) if r.weight is not None else 1.0)
            for r in reports
            if r.grade is not None
        ) / total_weight if total_weight > 0 else None
        sr.grade_generated_by_id = None  # system-generated
        sr.grade_generated_timestamp = datetime.now()
        # Guard: only advance to READY_TO_SIGN_OFF if a grade was actually computed.
        if sr.grade is None:
            current_app.logger.error(
                f"_check_tolerance_and_grade: computed grade is None for SubmitterReport "
                f"id={sr.id} — not advancing to READY_TO_SIGN_OFF"
            )
            return
        sr.workflow_state = SubmitterReportWorkflowStates.READY_TO_SIGN_OFF
    else:
        # Tolerance check required: mark out-of-tolerance and route to moderation
        sr.out_of_tolerance = True
        _emit_moderation_required_emails(sr)

        # Attempt to assign an existing ROLE_MODERATOR on the SubmissionRecord
        moderator_roles = [
            r
            for r in sr.record.roles.all()
            if r.role == SubmissionRoleTypesMixin.ROLE_MODERATOR
        ]
        if moderator_roles:
            chosen = random.choice(moderator_roles)
            _assign_moderator(sr, chosen)
        else:
            sr.workflow_state = SubmitterReportWorkflowStates.NEEDS_MODERATOR_ASSIGNED


def advance_submitter_report(sr: SubmitterReport) -> None:
    """
    Re-evaluate the lifecycle state of a SubmitterReport based on the current state of all
    attached MarkingReports.  Should be called after any change that may affect the state
    (grade submission, sign-off, feedback submission, moderator report submission).

    Does NOT commit the session — callers are responsible for committing.
    """
    # Turnitin override: an unresolved high-similarity score blocks all forward progress.
    # The SR must remain in REQUIRES_CONVENOR_INTERVENTION until the convenor resolves it.
    if (
        sr.record.turnitin_score is not None
        and sr.record.turnitin_score >= 25
        and not sr.turnitin_resolved
    ):
        sr.workflow_state = SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION
        return

    reports = sr.marking_reports.all()

    if not reports:
        return

    all_submitted = all(r.report_submitted for r in reports)
    all_signed_off = all(r.signed_off_id is not None for r in reports)
    all_feedback_ok = all(r.feedback_submitted for r in reports)

    if not all_submitted:
        return  # not ready to advance past AWAITING_GRADING_REPORTS

    if all_signed_off and all_feedback_ok:
        _check_tolerance_and_grade(sr, reports)
    elif all_signed_off:
        sr.workflow_state = SubmitterReportWorkflowStates.AWAITING_FEEDBACK
    else:
        sr.workflow_state = SubmitterReportWorkflowStates.AWAITING_RESPONSIBLE_SUPERVISOR_SIGNOFF


def schedule_close_marking_window(mr: MarkingReport) -> None:
    """
    Create a DatabaseSchedulerEntry (backed by a one-shot CrontabSchedule) to fire
    close_marking_window 24 hours after the marking report's grade_submitted_timestamp.

    The CrontabSchedule is constructed so that it matches the exact target minute/hour/day/month.
    The DatabaseSchedulerEntry's expires field is set to target + 1 hour so that it self-destructs
    after firing.  The task itself also deletes both rows on execution to avoid accumulation.

    Does NOT commit the session — callers are responsible for committing.
    """
    if mr.grade_submitted_timestamp is None:
        return

    target = mr.grade_submitted_timestamp + timedelta(hours=24)

    crontab = CrontabSchedule(
        minute=str(target.minute),
        hour=str(target.hour),
        day_of_month=str(target.day),
        month_of_year=str(target.month),
    )
    db.session.add(crontab)
    db.session.flush()  # materialise crontab.id

    entry = DatabaseSchedulerEntry(
        name=f"close_marking_window_mr{mr.id}_{target.strftime('%Y%m%d%H%M')}",
        task="app.tasks.markingevent.close_marking_window",
        crontab_id=crontab.id,
        expires=target + timedelta(hours=1),
        enabled=True,
    )
    db.session.add(entry)
    db.session.flush()  # materialise entry.id so we can pass it as an arg

    entry.args = [mr.id, entry.id]


def register_markingevent_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def initialize_marking_workflow(self, workflow_id):
        """
        Create SubmitterReport and MarkingReport instances for a newly created MarkingWorkflow.

        For each SubmissionRecord in the parent SubmissionPeriodRecord, one SubmitterReport is
        created. For each SubmissionRole on that record whose role matches the workflow's target
        role (with ROLE_SUPERVISOR and ROLE_RESPONSIBLE_SUPERVISOR treated as equivalent), one
        MarkingReport is created.
        """
        try:
            workflow: MarkingWorkflow = (
                db.session.query(MarkingWorkflow).filter_by(id=workflow_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if workflow is None:
            current_app.logger.error(
                f"initialize_marking_workflow: workflow id={workflow_id} not found in database"
            )
            return

        period = workflow.event.period
        wf_role = workflow.role
        pclass = workflow.event.pclass

        submitter_count = 0
        marking_count = 0

        try:
            for record in period.submissions.all():
                # Determine the correct initial state:
                # - requires_report=False: ready immediately (no asset check needed)
                # - requires_report=True: ready only if both report and processed_report already exist
                # NOTE: If the SubmissionRecord has turnitin_score >= 25 and the SubmitterReport
                # has turnitin_resolved=False, the state must be REQUIRES_CONVENOR_INTERVENTION
                # rather than READY_TO_DISTRIBUTE. The SubmitterReport cannot proceed past
                # REQUIRES_CONVENOR_INTERVENTION until the convenor resolves the Turnitin concern.
                if not workflow.requires_report:
                    if (
                        record.turnitin_score is not None
                        and record.turnitin_score >= 25
                    ):
                        initial_state = (
                            SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION
                        )
                    else:
                        initial_state = (
                            SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE
                        )
                elif record.report is not None and record.processed_report is not None:
                    if (
                        record.turnitin_score is not None
                        and record.turnitin_score >= 25
                    ):
                        initial_state = (
                            SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION
                        )
                    else:
                        initial_state = (
                            SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE
                        )
                else:
                    initial_state = SubmitterReportWorkflowStates.NOT_READY

                sr = SubmitterReport(
                    record_id=record.id,
                    workflow_id=workflow.id,
                    workflow_state=initial_state,
                    grade=None,
                    grade_generated_by_id=None,
                    grade_generated_timestamp=None,
                    signed_off_id=None,
                    signed_off_timestamp=None,
                    feedback_sent=False,
                    feedback_push_id=None,
                    feedback_push_timestamp=None,
                    creator_id=None,
                    creation_timestamp=datetime.now(),
                )
                db.session.add(sr)
                db.session.flush()  # materialise sr.id before creating MarkingReports
                submitter_count += 1

                # Determine which SubmissionRole instances on this record should receive a
                # MarkingReport, based on the workflow's target role.
                #
                # For ROLE_SUPERVISOR workflows:
                #   - If the record has BOTH ROLE_SUPERVISOR and ROLE_RESPONSIBLE_SUPERVISOR roles,
                #     generate MarkingReports only for ROLE_SUPERVISOR. The supervisor is responsible
                #     for the marking; the report will be routed to a ROLE_RESPONSIBLE_SUPERVISOR for
                #     final sign-off after the 24-hour window closes.
                #   - If the record has only ROLE_RESPONSIBLE_SUPERVISOR roles (no plain supervisor),
                #     generate MarkingReports for those instead.
                #   - If the record has only ROLE_SUPERVISOR roles, generate for those.
                # For ROLE_RESPONSIBLE_SUPERVISOR workflows:
                #   - Always generate MarkingReports only for ROLE_RESPONSIBLE_SUPERVISOR roles.
                all_roles = record.roles.all()
                if wf_role == SubmissionRoleTypesMixin.ROLE_SUPERVISOR:
                    has_supervisor = any(
                        r.role == SubmissionRoleTypesMixin.ROLE_SUPERVISOR for r in all_roles
                    )
                    has_responsible = any(
                        r.role == SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR
                        for r in all_roles
                    )
                    if has_supervisor and has_responsible:
                        eligible_roles = [
                            r
                            for r in all_roles
                            if r.role == SubmissionRoleTypesMixin.ROLE_SUPERVISOR
                        ]
                    elif has_responsible:
                        eligible_roles = [
                            r
                            for r in all_roles
                            if r.role == SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR
                        ]
                    else:
                        eligible_roles = [
                            r
                            for r in all_roles
                            if r.role == SubmissionRoleTypesMixin.ROLE_SUPERVISOR
                        ]
                elif wf_role == SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR:
                    eligible_roles = [
                        r
                        for r in all_roles
                        if r.role == SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR
                    ]
                else:
                    eligible_roles = [r for r in all_roles if r.role == wf_role]

                for role in eligible_roles:
                    mr = MarkingReport(
                        role_id=role.id,
                        submitter_report_id=sr.id,
                        report="{}",
                        distributed=False,
                        report_submitted=False,
                        feedback_submitted=False,
                        grade=None,
                        weight=role.weight,
                        feedback_positive=None,
                        feedback_improvement=None,
                        signed_off_id=None,
                        signed_off_timestamp=None,
                        feedback_timestamp=None,
                        creator_id=None,
                        creation_timestamp=datetime.now(),
                    )
                    db.session.add(mr)
                    marking_count += 1

            log_db_commit(
                f'Initialized MarkingWorkflow "{workflow.name}" (id={workflow_id}): '
                f"created {submitter_count} SubmitterReport(s) and {marking_count} MarkingReport(s) "
                f'for period "{period.display_name}"',
                endpoint=self.name,
                project_classes=pclass,
            )

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError in initialize_marking_workflow", exc_info=e
            )
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def advance_marking_workflow(self, record_id):
        """
        Advance SubmitterReport instances for a SubmissionRecord in two situations:

        1. NOT_READY → READY_TO_DISTRIBUTE (or REQUIRES_CONVENOR_INTERVENTION if Turnitin
           score >= 25 and unresolved).  Called after successful report processing.

        2. REQUIRES_CONVENOR_INTERVENTION → re-evaluated next state, when the Turnitin
           concern has since been resolved (turnitin_resolved=True).  For pre-distribution
           reports (no MarkingReports yet submitted) the state becomes READY_TO_DISTRIBUTE;
           for mid-lifecycle reports advance_submitter_report() picks the correct state.

        Called by process_report.finalize and by convenor.resolve_turnitin_issue.
        """
        try:
            record: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            current_app.logger.error(
                f"advance_marking_workflow: SubmissionRecord id={record_id} not found in database"
            )
            return

        advanced = 0
        try:
            for sr in record.submitter_reports.all():
                if sr.workflow_state == SubmitterReportWorkflowStates.NOT_READY:
                    workflow = sr.workflow
                    if workflow.requires_report:
                        # Only advance when both report and processed_report are present
                        if record.report is None or record.processed_report is None:
                            continue

                    # NOTE: If turnitin_score >= 25 and turnitin_resolved=False, transition to
                    # REQUIRES_CONVENOR_INTERVENTION instead of READY_TO_DISTRIBUTE.
                    # The SubmitterReport cannot proceed past REQUIRES_CONVENOR_INTERVENTION until
                    # the convenor resolves the Turnitin concern via convenor.resolve_turnitin_issue.
                    if (
                        record.turnitin_score is not None
                        and record.turnitin_score >= 25
                        and not sr.turnitin_resolved
                    ):
                        sr.workflow_state = (
                            SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION
                        )
                    else:
                        sr.workflow_state = (
                            SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE
                        )
                    advanced += 1

                elif (
                    sr.workflow_state == SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION
                    and sr.turnitin_resolved
                ):
                    # Turnitin concern resolved: re-evaluate using the full lifecycle evaluator
                    # to handle mid-lifecycle cases (MarkingReports already submitted/signed off).
                    advance_submitter_report(sr)

                    # If advance_submitter_report did not change the state (no MarkingReports
                    # submitted yet), the SR is still pre-distribution — move to READY_TO_DISTRIBUTE.
                    if (
                        sr.workflow_state
                        == SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION
                    ):
                        sr.workflow_state = SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE

                    advanced += 1

            if advanced > 0:
                log_db_commit(
                    f"Re-evaluated {advanced} SubmitterReport(s) for SubmissionRecord id={record_id} "
                    f"via advance_marking_workflow",
                    endpoint=self.name,
                )

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError in advance_marking_workflow", exc_info=e
            )
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30, name="app.tasks.markingevent.close_marking_window")
    def close_marking_window(self, marking_report_id, scheduler_entry_id):
        """
        Called 24 hours after a MarkingReport's grade_submitted_timestamp to close the editing
        window and advance the lifecycle state.

        Deletes its own DatabaseSchedulerEntry and linked CrontabSchedule on execution to
        prevent accumulation of one-off schedule rows.
        """
        # --- self-cleanup: remove the scheduler entry and its crontab ---
        try:
            entry = db.session.query(DatabaseSchedulerEntry).filter_by(id=scheduler_entry_id).first()
            if entry is not None:
                crontab_id = entry.crontab_id
                db.session.delete(entry)
                if crontab_id is not None:
                    crontab = db.session.query(CrontabSchedule).filter_by(id=crontab_id).first()
                    if crontab is not None:
                        db.session.delete(crontab)
                db.session.flush()
        except SQLAlchemyError as e:
            current_app.logger.exception(
                f"close_marking_window: could not delete scheduler entry #{scheduler_entry_id}",
                exc_info=e,
            )
            # Non-fatal — continue processing

        # --- load the MarkingReport ---
        try:
            mr: MarkingReport = db.session.query(MarkingReport).filter_by(id=marking_report_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if mr is None:
            current_app.logger.error(
                f"close_marking_window: MarkingReport id={marking_report_id} not found"
            )
            return

        if not mr.report_submitted:
            current_app.logger.info(
                f"close_marking_window: MarkingReport #{marking_report_id} not yet submitted; no action."
            )
            return

        try:
            role = mr.role
            pclass = mr.workflow.event.pclass

            if role.role in (
                SubmissionRoleTypesMixin.ROLE_MARKER,
                SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
            ):
                # Self sign-off: marker or responsible supervisor can sign off their own report
                mr.signed_off_id = role.id
                mr.signed_off_timestamp = datetime.now()

            elif role.role == SubmissionRoleTypesMixin.ROLE_SUPERVISOR:
                # Find ROLE_RESPONSIBLE_SUPERVISOR roles on the parent SubmissionRecord
                responsible_roles = [
                    r
                    for r in mr.submitter_report.record.roles.all()
                    if r.role == SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR
                ]
                if responsible_roles:
                    for resp_role in responsible_roles:
                        mr.responsible_supervisors.append(resp_role)
                    _emit_sign_off_emails(mr, responsible_roles)
                else:
                    # No responsible supervisor — treat as self-sign-off
                    mr.signed_off_id = role.id
                    mr.signed_off_timestamp = datetime.now()

            # Re-evaluate the parent SubmitterReport lifecycle state
            advance_submitter_report(mr.submitter_report)

            log_db_commit(
                f"Closed 24-hour marking window for MarkingReport #{marking_report_id} "
                f"(role: {role.role_as_str}, workflow: {mr.workflow.name})",
                endpoint=self.name,
                project_classes=pclass,
            )

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError in close_marking_window", exc_info=e
            )
            raise self.retry()
