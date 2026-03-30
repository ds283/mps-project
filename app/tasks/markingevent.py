#
# Created by David Seery on 30/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import MarkingReport, MarkingWorkflow, SubmitterReport
from ..models.markingevent import SubmitterReportWorkflowStates
from ..models.submissions import SubmissionRoleTypesMixin
from ..shared.workflow_logging import log_db_commit

_SUPERVISOR_ROLES = frozenset(
    {SubmissionRoleTypesMixin.ROLE_SUPERVISOR, SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR}
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
            workflow: MarkingWorkflow = db.session.query(MarkingWorkflow).filter_by(id=workflow_id).first()
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
                sr = SubmitterReport(
                    record_id=record.id,
                    workflow_id=workflow.id,
                    workflow_state=SubmitterReportWorkflowStates.NOT_READY,
                    grade=None,
                    grade_generated_by_id=None,
                    grade_generated_timestamp=None,
                    signed_off_id=None,
                    signed_off_timestamp=None,
                    feedback_sent=False,
                    feedback_push_id=None,
                    feedback_push_timestamp=None,
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
                        )
                        db.session.add(mr)
                        marking_count += 1

            log_db_commit(
                f'Initialized MarkingWorkflow "{workflow.name}" (id={workflow_id}): '
                f'created {submitter_count} SubmitterReport(s) and {marking_count} MarkingReport(s) '
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
