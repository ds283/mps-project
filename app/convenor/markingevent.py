#
# Created by David Seery on 25/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime
from functools import partial

from flask import current_app, flash, jsonify, redirect, request, url_for
from flask_login import current_user
from flask_security import roles_accepted
from sqlalchemy import and_, func
from sqlalchemy.exc import SQLAlchemyError

import app.ajax as ajax

from ..database import db
from ..models import (
    LiveMarkingScheme,
    MarkingEvent,
    MarkingReport,
    MarkingScheme,
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
from ..models.markingevent import SubmitterReportWorkflowStates
from ..shared.context.convenor_dashboard import get_convenor_dashboard_data
from ..shared.context.global_context import render_template_context
from ..shared.utils import redirect_url
from ..shared.validators import validate_is_convenor
from ..shared.workflow_logging import log_db_commit
from ..tools.ServerSideProcessing import ServerSideSQLHandler
from ..shared.forms.wtf_validators import (
    make_unique_marking_event_in_period,
    make_unique_marking_workflow_in_event,
)
from . import convenor
from .forms import (
    AddMarkingEventForm,
    AddMarkingSchemeForm,
    EditMarkingEventForm,
    EditMarkingSchemeForm,
    MarkingWorkflowFormFactory,
)


@convenor.route("/marking_events_inspector/<int:pclass_id>")
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def marking_events_inspector(pclass_id):
    """
    View MarkingEvent instances associated with closed SubmissionPeriodRecords
    for a given ProjectClass
    """
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # validate that the user has convenor access privileges
    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"]
    ):
        return redirect(redirect_url())

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/markingevent/marking_events_inspector.html",
        pane="assessment_archive",
        pclass=pclass,
        config=config,
        convenor_data=data,
    )


@convenor.route("/marking_events_ajax/<int:pclass_id>", methods=["POST"])
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def marking_events_ajax(pclass_id):
    """
    AJAX endpoint for MarkingEvent inspector DataTable
    """
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # validate that the user has convenor access privileges
    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"], message=False
    ):
        return jsonify({"error": "Access denied"}), 403

    # Build base query: MarkingEvents for closed SubmissionPeriodRecords belonging to this ProjectClass
    base_query = (
        db.session.query(MarkingEvent)
        .join(
            SubmissionPeriodRecord, SubmissionPeriodRecord.id == MarkingEvent.period_id
        )
        .join(
            ProjectClassConfig,
            ProjectClassConfig.id == SubmissionPeriodRecord.config_id,
        )
        .filter(
            and_(
                SubmissionPeriodRecord.config.has(pclass_id=pclass.id),
                SubmissionPeriodRecord.closed.is_(True),
            )
        )
    )

    columns = {
        "period": {
            "order": ProjectClassConfig.year,
            "search": SubmissionPeriodRecord.name,
        },
        "name": {"order": MarkingEvent.name, "search": MarkingEvent.name},
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.convenor.marking_event_data)


@convenor.route("/marking_workflow_inspector/<int:event_id>")
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def marking_workflow_inspector(event_id):
    """
    View MarkingWorkflow instances associated with a MarkingEvent
    """
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.period.config.project_class

    # validate that the user has convenor access privileges
    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"]
    ):
        return redirect(redirect_url())

    # Get return URL and text from request args
    url = request.args.get(
        "url", url_for("convenor.marking_events_inspector", pclass_id=pclass.id)
    )
    text = request.args.get("text", "Assessment archive")

    return render_template_context(
        "convenor/markingevent/marking_workflow_inspector.html",
        event=event,
        pclass=pclass,
        url=url,
        text=text,
    )


@convenor.route("/marking_workflow_ajax/<int:event_id>", methods=["POST"])
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def marking_workflow_ajax(event_id):
    """
    AJAX endpoint for MarkingWorkflow inspector DataTable
    """
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.period.config.project_class

    # Get URL parameters from the request
    from flask import request

    url = request.args.get("url", "")
    text = request.args.get("text", "")

    # validate that the user has convenor access privileges
    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"], message=False
    ):
        return jsonify({"error": "Access denied"}), 403

    base_query = db.session.query(MarkingWorkflow).filter(
        MarkingWorkflow.event_id == event_id
    )

    columns = {
        "name": {"order": MarkingWorkflow.name, "search": MarkingWorkflow.name},
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(
            partial(ajax.convenor.marking_workflow_data, url, text)
        )


@convenor.route("/submitter_reports_inspector/<int:workflow_id>")
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def submitter_reports_inspector(workflow_id):
    """
    View SubmitterReport instances associated with a MarkingWorkflow
    """
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.period.config.project_class

    # validate that the user has convenor access privileges
    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"]
    ):
        return redirect(redirect_url())

    # Get return URL and text from request args
    url = request.args.get(
        "url", url_for("convenor.marking_workflow_inspector", event_id=event.id)
    )
    text = request.args.get("text", "Marking workflows")

    # Compute per-state counts for the state timeline summary
    state_counts = dict(
        db.session.query(SubmitterReport.workflow_state, func.count())
        .filter(SubmitterReport.workflow_id == workflow_id)
        .group_by(SubmitterReport.workflow_state)
        .all()
    )

    state_labels = [
        (SubmitterReportWorkflowStates.NOT_READY, "Not ready"),
        (SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE, "Ready to distribute"),
        (SubmitterReportWorkflowStates.AWAITING_GRADING_REPORTS, "Awaiting grading reports"),
        (SubmitterReportWorkflowStates.AWAITING_RESPONSIBLE_SUPERVISOR_SIGNOFF, "Awaiting supervisor sign-off"),
        (SubmitterReportWorkflowStates.AWAITING_FEEDBACK, "Awaiting feedback"),
        (SubmitterReportWorkflowStates.REPORTS_OUT_OF_TOLERANCE, "Reports out of tolerance"),
        (SubmitterReportWorkflowStates.NEEDS_MODERATOR_ASSIGNED, "Needs moderator assigned"),
        (SubmitterReportWorkflowStates.AWAITING_MODERATOR_REPORT, "Awaiting moderator report"),
        (SubmitterReportWorkflowStates.READY_TO_GENERATE_GRADE, "Ready to generate grade"),
        (SubmitterReportWorkflowStates.READY_TO_SIGN_OFF, "Ready to sign off"),
        (SubmitterReportWorkflowStates.READY_TO_GENERATE_FEEDBACK, "Ready to generate feedback"),
        (SubmitterReportWorkflowStates.READY_TO_PUSH_FEEDBACK, "Ready to push feedback"),
        (SubmitterReportWorkflowStates.COMPLETED, "Completed"),
    ]

    return render_template_context(
        "convenor/markingevent/submitter_reports_inspector.html",
        workflow=workflow,
        event=event,
        pclass=pclass,
        url=url,
        text=text,
        state_counts=state_counts,
        state_labels=state_labels,
    )


@convenor.route("/submitter_reports_ajax/<int:workflow_id>", methods=["POST"])
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def submitter_reports_ajax(workflow_id):
    """
    AJAX endpoint for SubmitterReport inspector DataTable
    """
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.period.config.project_class

    # validate that the user has convenor access privileges
    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"], message=False
    ):
        return jsonify({"error": "Access denied"}), 403

    base_query = (
        db.session.query(SubmitterReport)
        .join(SubmissionRecord, SubmissionRecord.id == SubmitterReport.record_id)
        .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
        .join(StudentData, StudentData.id == SubmittingStudent.student_id)
        .join(User, User.id == StudentData.id)
        .filter(SubmitterReport.workflow_id == workflow_id)
    )

    student_col = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "search_collation": "utf8_general_ci",
        "order": [User.last_name, User.first_name],
    }

    columns = {
        "student": student_col,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.convenor.submitter_report_data)


@convenor.route("/marking_reports_inspector/<int:workflow_id>")
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def marking_reports_inspector(workflow_id):
    """
    View MarkingReport instances associated with a MarkingWorkflow
    """
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.period.config.project_class

    # validate that the user has convenor access privileges
    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"]
    ):
        return redirect(redirect_url())

    # Get return URL and text from request args
    url = request.args.get(
        "url", url_for("convenor.marking_workflow_inspector", event_id=event.id)
    )
    text = request.args.get("text", "Marking workflows")

    # Compute aggregate statistics for the summary row
    total_reports = workflow.number_marking_reports
    distributed_count = workflow.number_marking_reports_distributed
    submitted_count = (
        db.session.query(func.count(MarkingReport.id))
        .join(SubmitterReport, SubmitterReport.id == MarkingReport.submitter_report_id)
        .filter(
            SubmitterReport.workflow_id == workflow_id,
            MarkingReport.report_submitted.is_(True),
        )
        .scalar()
        or 0
    )
    feedback_count = workflow.number_marking_reports_with_feedback

    return render_template_context(
        "convenor/markingevent/marking_reports_inspector.html",
        workflow=workflow,
        event=event,
        pclass=pclass,
        url=url,
        text=text,
        total_reports=total_reports,
        distributed_count=distributed_count,
        submitted_count=submitted_count,
        feedback_count=feedback_count,
    )


@convenor.route("/marking_reports_ajax/<int:workflow_id>", methods=["POST"])
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def marking_reports_ajax(workflow_id):
    """
    AJAX endpoint for MarkingReport inspector DataTable
    """
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.period.config.project_class

    # validate that the user has convenor access privileges
    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"], message=False
    ):
        return jsonify({"error": "Access denied"}), 403

    base_query = (
        db.session.query(MarkingReport)
        .join(SubmitterReport, SubmitterReport.id == MarkingReport.submitter_report_id)
        .join(SubmissionRole, SubmissionRole.id == MarkingReport.role_id)
        .join(User, User.id == SubmissionRole.user_id)
        .filter(SubmitterReport.workflow_id == workflow_id)
    )

    marker_col = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "search_collation": "utf8_general_ci",
        "order": [User.last_name, User.first_name],
    }

    columns = {
        "marker": marker_col,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.convenor.marking_report_data)


@convenor.route("/marking_schemes_inspector/<int:pclass_id>")
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def inspect_marking_schemes(pclass_id):
    """
    View MarkingScheme instances attached to a given ProjectClass
    """
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"]
    ):
        return redirect(redirect_url())

    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/marking_events/marking_schemes_inspector.html",
        pclass=pclass,
        config=config,
        convenor_data=data,
    )


@convenor.route("/marking_schemes_ajax/<int:pclass_id>", methods=["POST"])
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def marking_schemes_ajax(pclass_id):
    """
    AJAX endpoint for MarkingScheme inspector DataTable
    """
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"], message=False
    ):
        return jsonify({"error": "Access denied"}), 403

    base_query = db.session.query(MarkingScheme).filter(
        MarkingScheme.pclass_id == pclass_id
    )

    columns = {
        "name": {"order": MarkingScheme.name, "search": MarkingScheme.name},
    }

    url = url_for("convenor.inspect_marking_schemes", pclass_id=pclass_id)
    text = "Marking schemes"

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(
            partial(ajax.convenor.marking_scheme_data, url, text)
        )


@convenor.route("/add_marking_scheme/<int:pclass_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def add_marking_scheme(pclass_id):
    """
    Create a new MarkingScheme for a given ProjectClass
    """
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.inspect_marking_schemes", pclass_id=pclass_id)
    )
    text = request.args.get("text", "Marking schemes")

    form = AddMarkingSchemeForm(request.form)

    if form.validate_on_submit():
        scheme = MarkingScheme(
            pclass_id=pclass_id,
            name=form.name.data,
            title=form.title.data,
            rubric=form.rubric.data,
            schema=form.schema.data,
            uses_standard_feedback=form.uses_standard_feedback.data,
            uses_tolerance=form.uses_tolerance.data,
            marker_tolerance=form.marker_tolerance.data,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            db.session.add(scheme)
            log_db_commit(
                f'Added new marking scheme "{scheme.name}" for project class "{pclass.name}"',
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add marking scheme due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(
            url_for("convenor.inspect_marking_schemes", pclass_id=pclass_id)
        )

    return render_template_context(
        "convenor/marking_events/edit_marking_scheme.html",
        form=form,
        scheme=None,
        pclass=pclass,
        title="Add new marking scheme",
        formtitle=f"Add new marking scheme for <strong>{pclass.name}</strong>",
        url=url,
        text=text,
    )


@convenor.route("/edit_marking_scheme/<int:scheme_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def edit_marking_scheme(scheme_id):
    """
    Edit an existing MarkingScheme
    """
    scheme: MarkingScheme = MarkingScheme.query.get_or_404(scheme_id)
    pclass: ProjectClass = scheme.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.inspect_marking_schemes", pclass_id=pclass.id)
    )
    text = request.args.get("text", "Marking schemes")

    form = EditMarkingSchemeForm(obj=scheme)

    if form.validate_on_submit():
        scheme.name = form.name.data
        scheme.title = form.title.data
        scheme.rubric = form.rubric.data
        scheme.schema = form.schema.data
        scheme.uses_standard_feedback = form.uses_standard_feedback.data
        scheme.uses_tolerance = form.uses_tolerance.data
        scheme.marker_tolerance = form.marker_tolerance.data
        scheme.last_edit_id = current_user.id
        scheme.last_edit_timestamp = datetime.now()

        try:
            log_db_commit(
                f'Saved changes to marking scheme "{scheme.name}" for project class "{pclass.name}"',
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(
            url_for("convenor.inspect_marking_schemes", pclass_id=pclass.id)
        )

    return render_template_context(
        "convenor/marking_events/edit_marking_scheme.html",
        form=form,
        scheme=scheme,
        pclass=pclass,
        title="Edit marking scheme",
        formtitle=f"Edit marking scheme for <strong>{pclass.name}</strong>",
        url=url,
        text=text,
    )


# ============================================================
#  MarkingEvent CRUD routes
# ============================================================


def _can_delete_marking_event(pclass: ProjectClass) -> bool:
    """Check whether the current user is allowed to delete MarkingEvent instances."""
    from flask_login import current_user

    if current_user.has_role("root"):
        return True
    if current_user.has_role("admin"):
        return pclass.tenant in current_user.tenants
    return False


@convenor.route("/period_marking_events_inspector/<int:period_id>")
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def period_marking_events_inspector(period_id):
    """
    Inspector for MarkingEvent instances associated with a specific SubmissionPeriodRecord.
    Unlike the archive view, this is not restricted to closed periods.
    """
    period: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(period_id)
    pclass: ProjectClass = period.config.project_class

    if not validate_is_convenor(pclass, allow_roles=["office", "external_examiner", "exam_board"]):
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.periods", id=pclass.id)
    )
    text = request.args.get("text", "Submission periods")

    can_delete = _can_delete_marking_event(pclass)

    return render_template_context(
        "convenor/markingevent/period_marking_events_inspector.html",
        period=period,
        pclass=pclass,
        url=url,
        text=text,
        can_delete=can_delete,
    )


@convenor.route("/period_marking_events_ajax/<int:period_id>", methods=["POST"])
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def period_marking_events_ajax(period_id):
    """AJAX endpoint for MarkingEvent CRUD inspector DataTable"""
    period: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(period_id)
    pclass: ProjectClass = period.config.project_class

    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"], message=False
    ):
        return jsonify({"error": "Access denied"}), 403

    url = request.args.get("url", url_for("convenor.periods", id=pclass.id))
    text = request.args.get("text", "Submission periods")
    can_delete = _can_delete_marking_event(pclass)

    base_query = db.session.query(MarkingEvent).filter(MarkingEvent.period_id == period_id)

    columns = {
        "name": {"order": MarkingEvent.name, "search": MarkingEvent.name},
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(
            partial(ajax.convenor.period_marking_event_data, url, text, can_delete)
        )


@convenor.route("/add_marking_event/<int:period_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def add_marking_event(period_id):
    """Create a new MarkingEvent for a given SubmissionPeriodRecord"""
    period: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(period_id)
    pclass: ProjectClass = period.config.project_class

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.period_marking_events_inspector", period_id=period_id)
    )
    text = request.args.get("text", "Marking events")

    form = AddMarkingEventForm(request.form)
    form.name.validators.append(make_unique_marking_event_in_period(period_id))

    if form.validate_on_submit():
        event = MarkingEvent(
            period_id=period_id,
            name=form.name.data,
            closed=False,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            db.session.add(event)
            log_db_commit(
                f'Added marking event "{event.name}" for period "{period.display_name}" '
                f'in project class "{pclass.name}"',
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add marking event due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url_for("convenor.period_marking_events_inspector", period_id=period_id))

    return render_template_context(
        "convenor/markingevent/edit_marking_event.html",
        form=form,
        event=None,
        period=period,
        pclass=pclass,
        title="Add marking event",
        formtitle=f"Add marking event for <strong>{period.display_name}</strong>",
        url=url,
        text=text,
    )


@convenor.route("/edit_marking_event/<int:event_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def edit_marking_event(event_id):
    """Edit an existing MarkingEvent"""
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    period: SubmissionPeriodRecord = event.period
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.period_marking_events_inspector", period_id=period.id)
    )
    text = request.args.get("text", "Marking events")

    form = EditMarkingEventForm(obj=event)
    form.name.validators.append(
        make_unique_marking_event_in_period(period.id, event=event)
    )

    if form.validate_on_submit():
        event.name = form.name.data
        event.last_edit_id = current_user.id
        event.last_edit_timestamp = datetime.now()

        try:
            log_db_commit(
                f'Saved changes to marking event "{event.name}" for period "{period.display_name}" '
                f'in project class "{pclass.name}"',
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url_for("convenor.period_marking_events_inspector", period_id=period.id))

    return render_template_context(
        "convenor/markingevent/edit_marking_event.html",
        form=form,
        event=event,
        period=period,
        pclass=pclass,
        title="Edit marking event",
        formtitle=f"Edit marking event for <strong>{period.display_name}</strong>",
        url=url,
        text=text,
    )


@convenor.route("/delete_marking_event/<int:event_id>")
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def delete_marking_event(event_id):
    """Danger-confirm page before deleting a MarkingEvent (admin/root only)"""
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass

    if not _can_delete_marking_event(pclass):
        flash("You do not have permission to delete marking events.", "error")
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.period_marking_events_inspector", period_id=event.period_id)
    )
    text = request.args.get("text", "Marking events")

    return render_template_context(
        "admin/danger_confirm.html",
        title="Delete marking event",
        panel_title="Delete marking event",
        message=f'<p>Are you sure you want to permanently delete the marking event '
                f'<strong>"{event.name}"</strong>?</p>'
                f'<p class="text-danger">This will also delete all associated workflows, '
                f'submitter reports, and marking reports. This action cannot be undone.</p>',
        action_url=url_for(
            "convenor.confirm_delete_marking_event", event_id=event_id, url=url, text=text
        ),
        submit_label="Delete marking event",
    )


@convenor.route("/confirm_delete_marking_event/<int:event_id>")
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def confirm_delete_marking_event(event_id):
    """Permanently delete a MarkingEvent and all its child records (admin/root only)"""
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass
    period_id = event.period_id

    if not _can_delete_marking_event(pclass):
        flash("You do not have permission to delete marking events.", "error")
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.period_marking_events_inspector", period_id=period_id)
    )

    event_name = event.name
    period_name = event.period.display_name

    try:
        # Delete in FK order: MarkingReports → SubmitterReports → MarkingWorkflows → MarkingEvent
        for workflow in event.workflows.all():
            for sr in workflow.submitter_reports.all():
                for mr in sr.marking_reports.all():
                    db.session.delete(mr)
                db.session.delete(sr)
            db.session.delete(workflow)
        db.session.delete(event)

        log_db_commit(
            f'Deleted marking event "{event_name}" from period "{period_name}" '
            f'in project class "{pclass.name}"',
            user=current_user,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not delete marking event due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url)


@convenor.route("/close_marking_event_confirm/<int:event_id>")
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def close_marking_event_confirm(event_id):
    """Danger-confirm page before closing a MarkingEvent"""
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.closed:
        flash("This marking event is already closed.", "info")
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.period_marking_events_inspector", period_id=event.period_id)
    )
    text = request.args.get("text", "Marking events")

    return render_template_context(
        "admin/danger_confirm.html",
        title="Close marking event",
        panel_title="Close marking event",
        message=f'<p>Are you sure you want to close the marking event '
                f'<strong>"{event.name}"</strong>?</p>'
                f'<p class="text-danger">Closing a marking event is a one-time operation. '
                f'Once closed, it cannot be reopened and no further changes can be made '
                f'to its workflows or reports.</p>',
        action_url=url_for("convenor.close_marking_event", event_id=event_id, url=url, text=text),
        submit_label="Close marking event",
    )


@convenor.route("/close_marking_event/<int:event_id>")
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def close_marking_event(event_id):
    """
    Close a MarkingEvent. Sets the closed flag. For now this is a stub;
    in future it will dispatch a Celery workflow to finalise the event.
    """
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass
    period_id = event.period_id

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.period_marking_events_inspector", period_id=period_id)
    )

    if event.closed:
        flash("This marking event is already closed.", "info")
        return redirect(url)

    try:
        event.closed = True
        event.last_edit_id = current_user.id
        event.last_edit_timestamp = datetime.now()

        log_db_commit(
            f'Closed marking event "{event.name}" for period "{event.period.display_name}" '
            f'in project class "{pclass.name}"',
            user=current_user,
            project_classes=pclass,
        )
        flash(f'Marking event "{event.name}" has been closed.', "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not close marking event due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url)


# ============================================================
#  MarkingWorkflow CRUD routes
# ============================================================


@convenor.route("/event_marking_workflows_inspector/<int:event_id>")
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def event_marking_workflows_inspector(event_id):
    """
    CRUD inspector for MarkingWorkflow instances belonging to an active (non-archive) MarkingEvent.
    """
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass, allow_roles=["office", "external_examiner", "exam_board"]):
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.period_marking_events_inspector", period_id=event.period_id)
    )
    text = request.args.get("text", "Marking events")

    can_edit = not event.closed

    return render_template_context(
        "convenor/markingevent/event_marking_workflows_inspector.html",
        event=event,
        pclass=pclass,
        url=url,
        text=text,
        can_edit=can_edit,
    )


@convenor.route("/event_marking_workflows_ajax/<int:event_id>", methods=["POST"])
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def event_marking_workflows_ajax(event_id):
    """AJAX endpoint for MarkingWorkflow CRUD inspector DataTable"""
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"], message=False
    ):
        return jsonify({"error": "Access denied"}), 403

    url = request.args.get("url", "")
    text = request.args.get("text", "")
    can_edit = not event.closed

    base_query = db.session.query(MarkingWorkflow).filter(MarkingWorkflow.event_id == event_id)

    columns = {
        "name": {"order": MarkingWorkflow.name, "search": MarkingWorkflow.name},
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(
            partial(ajax.convenor.event_marking_workflow_data, url, text, can_edit)
        )


@convenor.route("/add_marking_workflow/<int:event_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def add_marking_workflow(event_id):
    """Create a new MarkingWorkflow for a given MarkingEvent"""
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.closed:
        flash("Cannot add workflows to a closed marking event.", "error")
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.event_marking_workflows_inspector", event_id=event_id)
    )
    text = request.args.get("text", "Marking workflows")

    AddWorkflowForm, _ = MarkingWorkflowFormFactory(pclass, scheme_locked=False)
    form = AddWorkflowForm(request.form)
    form.name.validators.append(make_unique_marking_workflow_in_event(event_id))

    if form.validate_on_submit():
        scheme_id = None

        try:
            # Create a LiveMarkingScheme snapshot if a scheme was selected
            if form.scheme.data is not None:
                source = form.scheme.data
                live = LiveMarkingScheme(
                    parent_id=source.id,
                    name=source.name,
                    title=source.title,
                    rubric=source.rubric,
                    schema=source.schema,
                    uses_standard_feedback=source.uses_standard_feedback,
                    uses_tolerance=source.uses_tolerance,
                    marker_tolerance=source.marker_tolerance,
                )
                db.session.add(live)
                db.session.flush()
                scheme_id = live.id

            workflow = MarkingWorkflow(
                event_id=event_id,
                name=form.name.data,
                role=form.role.data,
                scheme_id=scheme_id,
                creator_id=current_user.id,
                creation_timestamp=datetime.now(),
            )
            workflow.notify_on_moderation_required = list(form.notify_on_moderation_required.data)
            workflow.notify_on_validation_failure = list(form.notify_on_validation_failure.data)

            db.session.add(workflow)
            db.session.flush()
            workflow_id = workflow.id

            log_db_commit(
                f'Added marking workflow "{workflow.name}" to event "{event.name}" '
                f'in project class "{pclass.name}"',
                user=current_user,
                project_classes=pclass,
            )

            # Dispatch Celery task to create SubmitterReport/MarkingReport instances
            celery = current_app.extensions["celery"]
            init_task = celery.tasks["app.tasks.markingevent.initialize_marking_workflow"]
            init_task.apply_async(args=(workflow_id,))

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add marking workflow due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url_for("convenor.event_marking_workflows_inspector", event_id=event_id))

    return render_template_context(
        "convenor/markingevent/edit_marking_workflow.html",
        form=form,
        workflow=None,
        event=event,
        pclass=pclass,
        title="Add marking workflow",
        formtitle=f"Add marking workflow to event <strong>{event.name}</strong>",
        url=url,
        text=text,
        scheme_locked=False,
    )


@convenor.route("/edit_marking_workflow/<int:workflow_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def edit_marking_workflow(workflow_id):
    """Edit an existing MarkingWorkflow"""
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.closed:
        flash("Cannot edit workflows in a closed marking event.", "error")
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.event_marking_workflows_inspector", event_id=event.id)
    )
    text = request.args.get("text", "Marking workflows")

    # Lock the scheme field if any MarkingReport has been distributed or has a non-empty report
    scheme_locked = any(
        mr.distributed or (mr.report and mr.report != "{}")
        for sr in workflow.submitter_reports.all()
        for mr in sr.marking_reports.all()
    )

    _, EditWorkflowForm = MarkingWorkflowFormFactory(pclass, scheme_locked=scheme_locked)
    form = EditWorkflowForm(obj=workflow)
    form.name.validators.append(make_unique_marking_workflow_in_event(event.id, workflow=workflow))

    if form.validate_on_submit():
        try:
            workflow.name = form.name.data
            workflow.last_edit_id = current_user.id
            workflow.last_edit_timestamp = datetime.now()

            # Update scheme if not locked
            if not scheme_locked:
                if form.scheme.data is not None:
                    source = form.scheme.data
                    # Always create a new LiveMarkingScheme snapshot on scheme change
                    live = LiveMarkingScheme(
                        parent_id=source.id,
                        name=source.name,
                        title=source.title,
                        rubric=source.rubric,
                        schema=source.schema,
                        uses_standard_feedback=source.uses_standard_feedback,
                        uses_tolerance=source.uses_tolerance,
                        marker_tolerance=source.marker_tolerance,
                    )
                    db.session.add(live)
                    db.session.flush()
                    workflow.scheme_id = live.id
                else:
                    workflow.scheme_id = None

            workflow.notify_on_moderation_required = list(form.notify_on_moderation_required.data)
            workflow.notify_on_validation_failure = list(form.notify_on_validation_failure.data)

            log_db_commit(
                f'Saved changes to marking workflow "{workflow.name}" in event "{event.name}" '
                f'in project class "{pclass.name}"',
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url_for("convenor.event_marking_workflows_inspector", event_id=event.id))

    return render_template_context(
        "convenor/markingevent/edit_marking_workflow.html",
        form=form,
        workflow=workflow,
        event=event,
        pclass=pclass,
        title="Edit marking workflow",
        formtitle=f"Edit marking workflow in event <strong>{event.name}</strong>",
        url=url,
        text=text,
        scheme_locked=scheme_locked,
    )


@convenor.route("/delete_marking_workflow/<int:workflow_id>")
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def delete_marking_workflow(workflow_id):
    """Danger-confirm page before deleting a MarkingWorkflow"""
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.closed:
        flash("Cannot delete workflows from a closed marking event.", "error")
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.event_marking_workflows_inspector", event_id=event.id)
    )
    text = request.args.get("text", "Marking workflows")

    return render_template_context(
        "admin/danger_confirm.html",
        title="Delete marking workflow",
        panel_title="Delete marking workflow",
        message=f'<p>Are you sure you want to permanently delete the marking workflow '
                f'<strong>"{workflow.name}"</strong>?</p>'
                f'<p class="text-danger">This will also delete all associated submitter reports '
                f'and marking reports. This action cannot be undone.</p>',
        action_url=url_for(
            "convenor.confirm_delete_marking_workflow", workflow_id=workflow_id, url=url, text=text
        ),
        submit_label="Delete marking workflow",
    )


@convenor.route("/confirm_delete_marking_workflow/<int:workflow_id>")
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def confirm_delete_marking_workflow(workflow_id):
    """Permanently delete a MarkingWorkflow and all its child records"""
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass
    event_id = event.id

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.closed:
        flash("Cannot delete workflows from a closed marking event.", "error")
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.event_marking_workflows_inspector", event_id=event_id)
    )

    workflow_name = workflow.name

    try:
        # Delete in FK order: MarkingReports → SubmitterReports → MarkingWorkflow
        for sr in workflow.submitter_reports.all():
            for mr in sr.marking_reports.all():
                db.session.delete(mr)
            db.session.delete(sr)
        db.session.delete(workflow)

        log_db_commit(
            f'Deleted marking workflow "{workflow_name}" from event "{event.name}" '
            f'in project class "{pclass.name}"',
            user=current_user,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not delete marking workflow due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url)


@convenor.route("/add_workflow_attachment/<int:workflow_id>")
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def add_workflow_attachment(workflow_id):
    """Show the list of available PeriodAttachments that can be added to this workflow"""
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.closed:
        flash("Cannot modify attachments in a closed marking event.", "error")
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.edit_marking_workflow", workflow_id=workflow_id)
    )
    text = request.args.get("text", "Edit workflow")

    # Get period attachments not already attached to this workflow
    already_attached_ids = {a.id for a in workflow.attachments}
    available = [
        a
        for a in event.period.attachments.all()
        if a.id not in already_attached_ids
    ]

    return render_template_context(
        "convenor/markingevent/add_workflow_attachment.html",
        workflow=workflow,
        event=event,
        pclass=pclass,
        available=available,
        url=url,
        text=text,
    )


@convenor.route("/confirm_add_workflow_attachment/<int:workflow_id>/<int:attachment_id>")
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def confirm_add_workflow_attachment(workflow_id, attachment_id):
    """Add a PeriodAttachment to a MarkingWorkflow"""
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    attachment: PeriodAttachment = PeriodAttachment.query.get_or_404(attachment_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.closed:
        flash("Cannot modify attachments in a closed marking event.", "error")
        return redirect(redirect_url())

    # Verify the attachment belongs to the same period
    if attachment.parent_id != event.period_id:
        flash("This attachment does not belong to the correct submission period.", "error")
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.edit_marking_workflow", workflow_id=workflow_id)
    )

    if attachment in workflow.attachments:
        flash("This attachment is already associated with this workflow.", "info")
        return redirect(url)

    try:
        workflow.attachments.append(attachment)
        log_db_commit(
            f'Added attachment "{attachment.attachment.filename if attachment.attachment else attachment.id}" '
            f'to workflow "{workflow.name}" in event "{event.name}" '
            f'in project class "{pclass.name}"',
            user=current_user,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not add attachment due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url)


@convenor.route("/remove_workflow_attachment/<int:workflow_id>/<int:attachment_id>")
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def remove_workflow_attachment(workflow_id, attachment_id):
    """Remove a PeriodAttachment from a MarkingWorkflow"""
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    attachment: PeriodAttachment = PeriodAttachment.query.get_or_404(attachment_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.closed:
        flash("Cannot modify attachments in a closed marking event.", "error")
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.edit_marking_workflow", workflow_id=workflow_id)
    )

    if attachment not in workflow.attachments:
        flash("This attachment is not associated with this workflow.", "info")
        return redirect(url)

    try:
        workflow.attachments.remove(attachment)
        log_db_commit(
            f'Removed attachment from workflow "{workflow.name}" in event "{event.name}" '
            f'in project class "{pclass.name}"',
            user=current_user,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not remove attachment due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url)
