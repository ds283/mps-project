#
# Created by David Seery on 13/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import date

from sqlalchemy import or_

from ...database import db
from ...models import (
    EnrollmentRecord,
    MarkingEvent,
    MarkingReport,
    MarkingWorkflow,
    MessageOfTheDay,
    ModeratorReport,
    SubmissionPeriodRecord,
    SubmissionRecord,
    SubmissionRole,
)
from ...models.markingevent import (
    MarkingEventWorkflowStates,
    SubmitterReport,
    SubmitterReportWorkflowStates,
    marking_report_to_responsible_supervisors,
)
from ...models.submissions import SubmissionRoleTypesMixin
from ..utils import get_approval_queue_data


def get_faculty_dashboard_data(user) -> dict:
    """
    Returns all context shared by every faculty dashboard pane route.

    Combines nav badge counts, enrolment list, system messages, approvals,
    and role flags into a single dict that can be splatted into
    render_template_context() alongside pane-specific variables.
    """
    # --- Nav badge counts ---

    pending_sign_off_reports = (
        db.session.query(MarkingReport)
        .join(
            marking_report_to_responsible_supervisors,
            marking_report_to_responsible_supervisors.c.marking_report_id == MarkingReport.id,
        )
        .join(SubmitterReport, SubmitterReport.id == MarkingReport.submitter_report_id)
        .filter(
            marking_report_to_responsible_supervisors.c.submission_role_id.in_(
                db.session.query(SubmissionRole.id).filter(SubmissionRole.user_id == user.id)
            ),
            MarkingReport.signed_off_id.is_(None),
            SubmitterReport.workflow_state != SubmitterReportWorkflowStates.DROPPED,
        )
        .all()
    )

    pending_moderator_reports = (
        db.session.query(ModeratorReport)
        .join(SubmissionRole, SubmissionRole.id == ModeratorReport.role_id)
        .join(SubmitterReport, SubmitterReport.id == ModeratorReport.submitter_report_id)
        .filter(
            SubmissionRole.user_id == user.id,
            ModeratorReport.report_submitted.is_(False),
            SubmitterReport.workflow_state != SubmitterReportWorkflowStates.DROPPED,
        )
        .all()
    )

    pending_marking_reports = (
        db.session.query(MarkingReport)
        .join(SubmissionRole, SubmissionRole.id == MarkingReport.role_id)
        .join(SubmitterReport, SubmitterReport.id == MarkingReport.submitter_report_id)
        .join(MarkingWorkflow, MarkingWorkflow.id == SubmitterReport.workflow_id)
        .join(MarkingEvent, MarkingEvent.id == MarkingWorkflow.event_id)
        .filter(
            SubmissionRole.user_id == user.id,
            MarkingEvent.workflow_state != MarkingEventWorkflowStates.CLOSED,
            SubmitterReport.workflow_state != SubmitterReportWorkflowStates.DROPPED,
            or_(
                MarkingReport.report_submitted.isnot(True),
                MarkingReport.feedback_submitted.isnot(True),
            ),
        )
        .all()
    )
    actionable_marking_count = sum(1 for r in pending_marking_reports if r.marking_form_is_open)

    my_students_pending_count = (
        db.session.query(SubmissionRecord)
        .join(SubmissionRole, SubmissionRole.submission_id == SubmissionRecord.id)
        .join(SubmissionPeriodRecord, SubmissionPeriodRecord.id == SubmissionRecord.period_id)
        .filter(
            SubmissionRole.user_id == user.id,
            SubmissionRole.role.in_(
                [
                    SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
                    SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
                ]
            ),
            SubmissionPeriodRecord.closed.is_(True),
            SubmissionRecord.report_grade.isnot(None),
            SubmissionRecord.exemplar_consent_granted_at.isnot(None),
            SubmissionRecord.exemplar_consent_withdrawn.is_(False),
            SubmissionRecord.exemplar_supervisor_approved.is_(None),
        )
        .distinct()
        .count()
    )

    # --- Enrolment list ---

    enrolments = []
    enrolment_panes = []
    enrolment_labels = {}
    fd = user.faculty_data
    if fd is not None:
        for record in fd.ordered_enrollments:
            pclass = record.pclass
            config = pclass.most_recent_config

            if pclass.active and pclass.publish and config is not None:
                include = False

                if (
                    (pclass.uses_supervisor and record.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED)
                    or (config.uses_marker and config.display_marker and record.marker_state == EnrollmentRecord.MARKER_ENROLLED)
                    or (
                        config.uses_presentations
                        and config.display_presentations
                        and record.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED
                    )
                ):
                    include = True
                else:
                    for n in range(config.number_submissions):
                        period = config.get_period(n + 1)
                        num_s = period.number_supervisor_records(user.id)
                        num_mk = period.number_marker_records(user.id)
                        num_mo = period.number_moderator_records(user.id)
                        num_p = period.number_presentation_assessor_records(user.id)

                        if (
                            (pclass.uses_supervisor and num_s > 0)
                            or (config.uses_marker and config.display_marker and num_mk > 0)
                            or (config.uses_moderator and config.display_marker and num_mo > 0)
                            or (config.uses_presentations and config.display_presentations and num_p > 0)
                        ):
                            include = True
                            break

                if include:
                    live_projects = config.live_projects.filter_by(owner_id=user.id)
                    enrolments.append({"config": config, "projects": live_projects, "record": record})
                    enrolment_panes.append(str(config.id))
                    enrolment_labels[str(config.id)] = config.name

    # --- System messages ---

    messages = []
    if fd is not None:
        for message in (
            db.session.query(MessageOfTheDay)
            .filter(
                MessageOfTheDay.show_faculty,
                ~MessageOfTheDay.dismissed_by.any(id=user.id),
            )
            .order_by(MessageOfTheDay.issue_date.desc())
            .all()
        ):
            include = message.project_classes.first() is None
            if not include:
                for pcl in message.project_classes:
                    if fd.is_enrolled(pcl):
                        include = True
                        break
            if include:
                messages.append(message)

    return {
        # Nav badge counts (used by nav.html for pill badges)
        "pending_sign_off_reports": pending_sign_off_reports,
        "pending_moderator_reports": pending_moderator_reports,
        "pending_marking_reports": pending_marking_reports,
        "actionable_marking_count": actionable_marking_count,
        "my_students_pending_count": my_students_pending_count,
        # Enrolment list (used by nav.html + pane templates)
        "enrolments": enrolments,
        "enrolment_panes": enrolment_panes,
        "enrolment_labels": enrolment_labels,
        "num_enrolments": len(enrolments),
        # System messages
        "messages": messages,
        # Approvals + role flags
        "approvals_data": get_approval_queue_data(),
        "is_user_approver": user.has_role("user_approver"),
        "is_project_approver": user.has_role("project_approver"),
        # Misc shared state
        "today": date.today(),
    }
