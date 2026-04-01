#
# Created by David Seery on 30/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from datetime import datetime

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import MarkingReport, MarkingWorkflow, SubmitterReport
from ..models.markingevent import SubmitterReportWorkflowStates
from ..models.submissions import SubmissionRecord, SubmissionRoleTypesMixin
from ..shared.workflow_logging import log_db_commit

_SUPERVISOR_ROLES = frozenset(
    {
        SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
        SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
    }
)


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

                for role in record.roles.all():
                    if wf_role in _SUPERVISOR_ROLES:
                        matches = role.role in _SUPERVISOR_ROLES
                    else:
                        matches = role.role == wf_role

                    if matches:
                        mr = MarkingReport(
                            role_id=role.id,
                            submitter_report_id=sr.id,
                            report="{}",
                            distributed=False,
                            report_submitted=False,
                            feedback_submitted=False,
                            grade=None,
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
        Advance any SubmitterReport instances for a SubmissionRecord from NOT_READY to
        READY_TO_DISTRIBUTE, where the preconditions for the associated MarkingWorkflow are met.

        Called by the process_report.finalize task after successful report processing.
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
                if sr.workflow_state != SubmitterReportWorkflowStates.NOT_READY:
                    continue

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

            if advanced > 0:
                log_db_commit(
                    f"Advanced {advanced} SubmitterReport(s) to READY_TO_DISTRIBUTE or "
                    f"REQUIRES_CONVENOR_INTERVENTION for SubmissionRecord id={record_id}",
                    endpoint=self.name,
                )

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError in advance_marking_workflow", exc_info=e
            )
            raise self.retry()
