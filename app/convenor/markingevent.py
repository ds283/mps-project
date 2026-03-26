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
    MarkingEvent,
    MarkingReport,
    MarkingScheme,
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
from ..shared.utils import redirect_url
from ..shared.validators import validate_is_convenor
from ..tools.ServerSideProcessing import ServerSideSQLHandler
from . import convenor
from .forms import AddMarkingSchemeForm, EditMarkingSchemeForm


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
            db.session.commit()
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
            db.session.commit()
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
