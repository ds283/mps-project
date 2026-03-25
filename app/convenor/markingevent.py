#
# Created by David Seery on 25/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import json
from functools import partial

from flask import flash, jsonify, redirect, request, url_for
from flask_security import current_user, roles_accepted
from sqlalchemy import and_, func

import app.ajax as ajax

from ..database import db
from ..models import (
    MarkingEvent,
    MarkingReport,
    MarkingWorkflow,
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
from ..shared.context.convenor_dashboard import get_convenor_dashboard_data
from ..shared.context.global_context import render_template_context
from ..shared.utils import get_current_year, redirect_url
from ..shared.validators import validate_is_convenor
from ..tools.ServerSideProcessing import ServerSideSQLHandler
from . import convenor


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
        .filter(
            and_(
                SubmissionPeriodRecord.config.has(pclass_id=pclass.id),
                SubmissionPeriodRecord.closed == True,
            )
        )
    )

    columns = {
        "period": {
            "order": SubmissionPeriodRecord.name,
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

    return render_template_context(
        "convenor/markingevent/submitter_reports_inspector.html",
        workflow=workflow,
        event=event,
        pclass=pclass,
        url=url,
        text=text,
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

    return render_template_context(
        "convenor/markingevent/marking_reports_inspector.html",
        workflow=workflow,
        event=event,
        pclass=pclass,
        url=url,
        text=text,
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
