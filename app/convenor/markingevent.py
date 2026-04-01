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

from celery import chain as celery_chain
from flask import current_app, flash, jsonify, redirect, request, url_for
from flask_login import current_user
from flask_security import roles_accepted
from sqlalchemy import and_, func
from sqlalchemy.exc import SQLAlchemyError

import app.ajax as ajax

from ..database import db
from ..models import (
    EmailTemplate,
    LiveMarkingScheme,
    MarkingEvent,
    MarkingReport,
    MarkingScheme,
    MarkingWorkflow,
    PeriodAttachment,
    ProjectClass,
    ProjectClassConfig,
    StudentData,
    SubmissionAttachment,
    SubmissionPeriodRecord,
    SubmissionRecord,
    SubmissionRole,
    SubmittedAsset,
    SubmitterReport,
    SubmittingStudent,
    User,
)
from ..models.markingevent import ConvenorAction, SubmitterReportWorkflowStates
from ..shared.asset_tools import AssetUploadManager
from ..shared.context.convenor_dashboard import get_convenor_dashboard_data
from ..shared.context.global_context import render_template_context
from ..shared.forms.wtf_validators import (
    make_unique_marking_event_in_period,
    make_unique_marking_scheme_in_pclass,
    make_unique_marking_workflow_in_event,
    make_unique_marking_workflow_key_in_event,
    make_valid_marking_targets,
)
from ..shared.security import validate_nonce
from ..shared.utils import redirect_url
from ..shared.validators import validate_is_convenor
from ..shared.workflow_logging import log_db_commit
from ..tasks.thumbnails import dispatch_thumbnail_task
from ..tools.ServerSideProcessing import ServerSideSQLHandler
from . import convenor
from .forms import (
    AddMarkingEventForm,
    AddMarkingSchemeForm,
    AssignModeratorFormFactory,
    EditMarkingEventForm,
    EditMarkingSchemeForm,
    EnterTurnitinScoreForm,
    MarkingReportPropertiesForm,
    MarkingWorkflowFormFactory,
    ResolveTurnitinForm,
    TestMarkingEventFormFactory,
)


def _assign_workflow_template(workflow: MarkingWorkflow, pclass: ProjectClass) -> None:
    """
    Auto-assign an email template to a MarkingWorkflow based on its role.
    Called at workflow creation time. Only assigns for ROLE_MARKER, ROLE_SUPERVISOR, and
    ROLE_RESPONSIBLE_SUPERVISOR; other roles are left without a template.
    """
    from ..models.submissions import SubmissionRoleTypesMixin

    supervisor_roles = frozenset(
        {
            SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
            SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
        }
    )
    if workflow.role == SubmissionRoleTypesMixin.ROLE_MARKER:
        template_type = EmailTemplate.MARKING_MARKER
    elif workflow.role in supervisor_roles:
        template_type = EmailTemplate.MARKING_SUPERVISOR
    else:
        return  # no template for other roles

    template = EmailTemplate.find_template_(template_type, pclass=pclass)
    if template is not None:
        workflow.template = template


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
        "convenor/markingevent/assessment_archive_inspector.html",
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

    from ..ajax.archive.marking_events import (
        marking_event_data as archive_marking_event_data,
    )

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(archive_marking_event_data)


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

    # validate that the user has convenor access privileges
    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"], message=False
    ):
        return jsonify({"error": "Access denied"}), 403

    # Use the current inspector page as the return URL for row-level action links
    url = url_for("convenor.marking_workflow_inspector", event_id=event_id)
    text = "Marking workflows"

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
        (
            SubmitterReportWorkflowStates.AWAITING_GRADING_REPORTS,
            "Awaiting grading reports",
        ),
        (
            SubmitterReportWorkflowStates.AWAITING_RESPONSIBLE_SUPERVISOR_SIGNOFF,
            "Awaiting supervisor sign-off",
        ),
        (SubmitterReportWorkflowStates.AWAITING_FEEDBACK, "Awaiting feedback"),
        # (
        #     SubmitterReportWorkflowStates.REPORTS_OUT_OF_TOLERANCE,
        #     "Reports out of tolerance",
        # ),
        (
            SubmitterReportWorkflowStates.NEEDS_MODERATOR_ASSIGNED,
            "Needs moderator assigned",
        ),
        (
            SubmitterReportWorkflowStates.AWAITING_MODERATOR_REPORT,
            "Awaiting moderator report",
        ),
        (
            SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION,
            "Requires convenor intervention",
        ),
        # (
        #     SubmitterReportWorkflowStates.READY_TO_GENERATE_GRADE,
        #     "Ready to generate grade",
        # ),
        (SubmitterReportWorkflowStates.READY_TO_SIGN_OFF, "Ready to sign off"),
        (
            SubmitterReportWorkflowStates.READY_TO_GENERATE_FEEDBACK,
            "Ready to generate feedback",
        ),
        (
            SubmitterReportWorkflowStates.READY_TO_PUSH_FEEDBACK,
            "Ready to push feedback",
        ),
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


@convenor.route("/resolve_turnitin/<int:submitter_report_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def resolve_turnitin_issue(submitter_report_id):
    """
    GET:  Display Turnitin score details and a comment form for the convenor to record
          their review decision for a SubmitterReport with similarity score >= 25%.
    POST: Set turnitin_resolved=True, record the comment, timestamp and resolving user,
          then transition the SubmitterReport from REQUIRES_CONVENOR_INTERVENTION back to
          READY_TO_DISTRIBUTE if it is currently in that blocking state.

    NOTE: A SubmitterReport in REQUIRES_CONVENOR_INTERVENTION cannot proceed to
    AWAITING_GRADING_REPORTS or any subsequent state until this resolution is recorded.
    """
    sr: SubmitterReport = SubmitterReport.query.get_or_404(submitter_report_id)
    workflow: MarkingWorkflow = sr.workflow
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass, allow_roles=["office"]):
        return redirect(redirect_url())

    url = request.args.get(
        "url",
        url_for("convenor.submitter_reports_inspector", workflow_id=workflow.id),
    )
    text = request.args.get("text", "Submitter reports")

    form = ResolveTurnitinForm(request.form)

    if form.validate_on_submit():
        try:
            sr.turnitin_resolved = True
            sr.turnitin_resolved_comment = form.comment.data
            sr.turnitin_resolved_timestamp = datetime.now()
            sr.turnitin_resolved_id = current_user.id

            log_db_commit(
                f"Convenor resolved Turnitin concern for SubmitterReport id={sr.id} "
                f"(student: {sr.student.user.name}, workflow: {workflow.name})",
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError in resolve_turnitin_issue", exc_info=e
            )
            flash("A database error occurred. Please try again.", "danger")
            return redirect(url)

        # Re-evaluate the lifecycle state for all SubmitterReports on this submission record.
        # advance_marking_workflow handles both pre-distribution (→ READY_TO_DISTRIBUTE) and
        # mid-lifecycle (delegates to advance_submitter_report) Turnitin resolution cases.
        celery = current_app.extensions["celery"]
        advance_wf = celery.tasks["app.tasks.markingevent.advance_marking_workflow"]
        advance_wf.apply_async(args=[sr.record.id])

        flash("Turnitin resolution recorded successfully.", "success")
        return redirect(url)

    return render_template_context(
        "convenor/markingevent/resolve_turnitin.html",
        form=form,
        report=sr,
        workflow=workflow,
        event=event,
        pclass=pclass,
        url=url,
        text=text,
    )


@convenor.route("/refetch_turnitin_from_canvas/<int:record_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def refetch_turnitin_from_canvas(record_id):
    """Queue a Celery task to re-fetch the Turnitin similarity data for a SubmissionRecord from Canvas."""
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(record_id)
    period: SubmissionPeriodRecord = record.period
    pclass: ProjectClass = period.config.project_class

    if not validate_is_convenor(pclass, allow_roles=["office"]):
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.marking_events_inspector", pclass_id=pclass.id)
    )

    if not record.canvas_turnitin_refetchable:
        flash(
            "Canvas integration is not available for this submission record.", "warning"
        )
        return redirect(url)

    try:
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.canvas.fetch_turnitin_data_for_record"]
        task.apply_async(args=[record_id])
        flash("Turnitin re-fetch from Canvas has been queued.", "success")
    except Exception as e:
        current_app.logger.exception(
            "Error queuing fetch_turnitin_data_for_record", exc_info=e
        )
        flash(
            "Could not queue Turnitin re-fetch. Please contact a system administrator.",
            "error",
        )

    return redirect(url)


@convenor.route("/enter_turnitin_score/<int:record_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def enter_turnitin_score(record_id):
    """Manually enter a Turnitin similarity score for a SubmissionRecord."""
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(record_id)
    period: SubmissionPeriodRecord = record.period
    pclass: ProjectClass = period.config.project_class

    if not validate_is_convenor(pclass, allow_roles=["office"]):
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.marking_events_inspector", pclass_id=pclass.id)
    )
    text = request.args.get("text", "Marking events")

    form = EnterTurnitinScoreForm(request.form)

    if form.validate_on_submit():
        try:
            record.turnitin_score = form.turnitin_score.data
            record.turnitin_web_overlap = form.turnitin_web_overlap.data
            record.turnitin_publication_overlap = form.turnitin_publication_overlap.data
            record.turnitin_student_overlap = form.turnitin_student_overlap.data

            similarity_file = request.files.get("similarity_report")
            if similarity_file and similarity_file.filename:
                with db.session.no_autoflush:
                    asset = SubmittedAsset(
                        timestamp=datetime.now(),
                        uploaded_id=current_user.id,
                        expiry=None,
                        target_name=similarity_file.filename,
                        license=None,
                    )
                    object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
                    with AssetUploadManager(
                        asset,
                        data=similarity_file.stream.read(),
                        storage=object_store,
                        audit_data=f"enter_turnitin_score: similarity report upload (record id #{record.id})",
                        length=similarity_file.content_length,
                        mimetype=similarity_file.content_type,
                        validate_nonce=validate_nonce,
                    ):
                        pass

                db.session.add(asset)
                db.session.flush()

                dispatch_thumbnail_task(asset)

                attachment = SubmissionAttachment(
                    parent_id=record.id,
                    attachment_id=asset.id,
                    description="Turnitin similarity report",
                    type=SubmissionAttachment.ATTACHMENT_SIMILARITY_REPORT,
                    publish_to_students=False,
                    include_marker_emails=False,
                    include_supervisor_emails=False,
                )
                db.session.add(attachment)

                asset.grant_user(current_user)
                for role in record.roles:
                    asset.grant_user(role.user)
                asset.grant_roles(
                    [
                        "office",
                        "convenor",
                        "moderator",
                        "exam_board",
                        "external_examiner",
                    ]
                )

            log_db_commit(
                f"Convenor manually entered Turnitin score={record.turnitin_score} "
                f"for SubmissionRecord id={record.id}",
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError in enter_turnitin_score", exc_info=e
            )
            flash("A database error occurred. Please try again.", "danger")
            return redirect(url)

        flash("Turnitin score recorded successfully.", "success")
        return redirect(url)

    # Pre-populate form with existing values if any
    if request.method == "GET":
        form.turnitin_score.data = record.turnitin_score
        form.turnitin_web_overlap.data = record.turnitin_web_overlap
        form.turnitin_publication_overlap.data = record.turnitin_publication_overlap
        form.turnitin_student_overlap.data = record.turnitin_student_overlap

    return render_template_context(
        "convenor/markingevent/enter_turnitin_score.html",
        form=form,
        record=record,
        period=period,
        pclass=pclass,
        url=url,
        text=text,
    )


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

    # Collect web validation failures from submitted marking reports
    import json as _json

    web_validation_failures = []
    for mr in workflow.marking_reports:
        if mr.report_submitted and mr.report and mr.report != "{}":
            try:
                blob = _json.loads(mr.report)
                failures = blob.get("validation_failures", [])
                if failures:
                    web_validation_failures.append({"report": mr, "failures": failures})
            except Exception:
                pass

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
        web_validation_failures=web_validation_failures,
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
        "convenor/markingevent/marking_schemes_inspector.html",
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
    form.name.validators.append(make_unique_marking_scheme_in_pclass(pclass_id))

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
        "convenor/markingevent/edit_marking_scheme.html",
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
    form.name.validators.append(make_unique_marking_scheme_in_pclass(pclass.id, name=scheme.name))

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
        "convenor/markingevent/edit_marking_scheme.html",
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

    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"]
    ):
        return redirect(redirect_url())

    url = request.args.get("url", url_for("convenor.periods", id=pclass.id))
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

    base_query = db.session.query(MarkingEvent).filter(
        MarkingEvent.period_id == period_id
    )

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
            deadline=form.deadline.data,
            targets="{}",
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

        return redirect(
            url_for("convenor.period_marking_events_inspector", period_id=period_id)
        )

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

    # build fiducial list of key->value assignments used to test the conflation rules for each target
    fiducial = {wf.key: 1.0 for wf in event.workflows}

    form = EditMarkingEventForm(obj=event)
    form.name.validators.append(
        make_unique_marking_event_in_period(period.id, name=event.name)
    )
    form.targets.validators.append(
        make_valid_marking_targets(fiducial)
    )

    if form.validate_on_submit():
        event.name = form.name.data
        event.deadline = form.deadline.data
        event.targets = form.targets.data or None
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

        return redirect(
            url_for("convenor.period_marking_events_inspector", period_id=period.id)
        )

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
        "url",
        url_for("convenor.period_marking_events_inspector", period_id=event.period_id),
    )
    text = request.args.get("text", "Marking events")

    return render_template_context(
        "admin/danger_confirm.html",
        title="Delete marking event",
        panel_title="Delete marking event",
        message=f"<p>Are you sure you want to permanently delete the marking event "
        f'<strong>"{event.name}"</strong>?</p>'
        f'<p class="text-danger">This will also delete all associated workflows, '
        f"submitter reports, and marking reports. This action cannot be undone.</p>",
        action_url=url_for(
            "convenor.confirm_delete_marking_event",
            event_id=event_id,
            url=url,
            text=text,
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
        "url",
        url_for("convenor.period_marking_events_inspector", period_id=event.period_id),
    )
    text = request.args.get("text", "Marking events")

    return render_template_context(
        "admin/danger_confirm.html",
        title="Close marking event",
        panel_title="Close marking event",
        message=f"<p>Are you sure you want to close the marking event "
        f'<strong>"{event.name}"</strong>?</p>'
        f'<p class="text-danger">Closing a marking event is a one-time operation. '
        f"Once closed, it cannot be reopened and no further changes can be made "
        f"to its workflows or reports.</p>",
        action_url=url_for(
            "convenor.close_marking_event", event_id=event_id, url=url, text=text
        ),
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

    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"]
    ):
        return redirect(redirect_url())

    url = request.args.get(
        "url",
        url_for("convenor.period_marking_events_inspector", period_id=event.period_id),
    )
    text = request.args.get("text", "Marking events")

    can_edit = not event.closed

    event_url = url_for("convenor.send_marking_emails_for_event", event_id=event_id)
    open_event_url = (
        url_for("convenor.open_marking_event", event_id=event_id)
        if not event.open
        else None
    )
    actions = event.get_convenor_actions(
        event_url=event_url, open_event_url=open_event_url
    )

    # Add per-workflow Turnitin CTAs for unresolved high-similarity scores and missing data.
    # Computed here (not in the model) so that url_for() can be called without
    # introducing routing knowledge into the model layer.
    # Only surface these CTAs while the event is still open.
    if not event.closed:
        for workflow in event.workflows:
            workflow_url = url_for(
                "convenor.submitter_reports_inspector",
                workflow_id=workflow.id,
                url=url_for(
                    "convenor.event_marking_workflows_inspector", event_id=event_id
                ),
                text="Marking workflows",
            )

            # CTA for unresolved high similarity scores
            unresolved = (
                db.session.query(SubmitterReport)
                .join(
                    SubmissionRecord, SubmissionRecord.id == SubmitterReport.record_id
                )
                .filter(
                    SubmitterReport.workflow_id == workflow.id,
                    SubmissionRecord.turnitin_score >= 25,
                    SubmitterReport.turnitin_resolved == False,  # noqa: E712
                )
                .count()
            )
            if unresolved > 0:
                n = unresolved
                actions.append(
                    ConvenorAction(
                        severity="warning",
                        title=f"Turnitin review required: {workflow.name}",
                        description=(
                            f"{n} submitter report{'s' if n != 1 else ''} in this workflow "
                            f"{'have' if n != 1 else 'has'} a Turnitin similarity score \u226525% "
                            f"and require{'s' if n == 1 else ''} convenor review before marking "
                            f"can proceed."
                        ),
                        action_url=workflow_url,
                        action_label="Review Turnitin scores",
                    )
                )

            # CTA for missing Turnitin data
            missing = (
                db.session.query(SubmitterReport)
                .join(
                    SubmissionRecord, SubmissionRecord.id == SubmitterReport.record_id
                )
                .filter(
                    SubmitterReport.workflow_id == workflow.id,
                    SubmissionRecord.turnitin_score == None,  # noqa: E711
                )
                .count()
            )
            if missing > 0:
                n = missing
                actions.append(
                    ConvenorAction(
                        severity="secondary",
                        title=f"Missing Turnitin data: {workflow.name}",
                        description=(
                            f"{n} submitter report{'s' if n != 1 else ''} in this workflow "
                            f"{'are' if n != 1 else 'is'} missing Turnitin similarity data. "
                            f"You can re-fetch from Canvas or enter scores manually."
                        ),
                        action_url=workflow_url,
                        action_label="Review submitter reports",
                    )
                )

    return render_template_context(
        "convenor/markingevent/event_marking_workflows_inspector.html",
        event=event,
        pclass=pclass,
        url=url,
        text=text,
        can_edit=can_edit,
        actions=actions,
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

    can_edit = not event.closed

    # Use the current inspector page as the return URL for row-level action links
    url = url_for("convenor.event_marking_workflows_inspector", event_id=event_id)
    text = "Marking workflows"

    base_query = db.session.query(MarkingWorkflow).filter(
        MarkingWorkflow.event_id == event_id
    )

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

    AddWorkflowForm, _ = MarkingWorkflowFormFactory(
        pclass, scheme_locked=False, event=event
    )
    form = AddWorkflowForm(request.form)
    form.name.validators.append(make_unique_marking_workflow_in_event(event_id))
    form.key.validators.append(make_unique_marking_workflow_key_in_event(event_id))

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
                    creator_id=current_user.id,
                    creation_timestamp=datetime.now(),
                )
                db.session.add(live)
                db.session.flush()
                scheme_id = live.id

            workflow = MarkingWorkflow(
                event_id=event_id,
                name=form.name.data,
                key=form.key.data,
                role=form.role.data,
                scheme_id=scheme_id,
                requires_report=form.requires_report.data,
                deadline=form.deadline.data,
                creator_id=current_user.id,
                creation_timestamp=datetime.now(),
            )
            workflow.notify_on_moderation_required = list(
                form.notify_on_moderation_required.data
            )
            workflow.notify_on_validation_failure = list(
                form.notify_on_validation_failure.data
            )

            # Auto-assign email template based on role
            _assign_workflow_template(workflow, pclass)

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
            init_task = celery.tasks[
                "app.tasks.markingevent.initialize_marking_workflow"
            ]
            init_task.apply_async(args=(workflow_id,))

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add marking workflow due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(
            url_for("convenor.event_marking_workflows_inspector", event_id=event_id)
        )

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

    _, EditWorkflowForm = MarkingWorkflowFormFactory(
        pclass, scheme_locked=scheme_locked, event=event
    )
    form = EditWorkflowForm(obj=workflow)

    # Don't validate `scheme` if the mark scheme is locked
    # The browser typically doesn't pass back its value in the form, so validation fails.
    # We achieve this by a monkey patch
    if scheme_locked:
        setattr(form.scheme, "pre_validate", lambda field: None)

    form.name.validators.append(
        make_unique_marking_workflow_in_event(event.id, name=workflow.name)
    )
    form.key.validators.append(
        make_unique_marking_workflow_key_in_event(event.id, key=workflow.key)
    )

    # On GET, pre-populate scheme with the parent MarkingScheme (not the LiveMarkingScheme snapshot),
    # so it matches the choices in the QuerySelectField.
    if request.method == "GET":
        form.scheme.data = workflow.scheme.parent if workflow.scheme else None

    if form.validate_on_submit():
        try:
            workflow.name = form.name.data
            workflow.key = form.key.data
            workflow.deadline = form.deadline.data
            workflow.last_edit_id = current_user.id
            workflow.last_edit_timestamp = datetime.now()

            # Update scheme if not locked
            if not scheme_locked:
                new_scheme = form.scheme.data  # a MarkingScheme or None
                if new_scheme is not None:
                    if (
                        workflow.scheme is None
                        or new_scheme.id != workflow.scheme.parent_id
                    ):
                        # Scheme has changed — replace the LiveMarkingScheme snapshot.
                        # Delete the old snapshot first to avoid a unique-constraint violation
                        # on scheme_id and to prevent orphaned rows.
                        old_live = workflow.scheme
                        live = LiveMarkingScheme(
                            parent_id=new_scheme.id,
                            name=new_scheme.name,
                            title=new_scheme.title,
                            rubric=new_scheme.rubric,
                            schema=new_scheme.schema,
                            uses_standard_feedback=new_scheme.uses_standard_feedback,
                            uses_tolerance=new_scheme.uses_tolerance,
                            marker_tolerance=new_scheme.marker_tolerance,
                            creator_id=current_user.id,
                            creation_timestamp=datetime.now(),
                        )
                        workflow.scheme_id = None
                        if old_live is not None:
                            db.session.delete(old_live)
                        db.session.add(live)
                        db.session.flush()
                        workflow.scheme_id = live.id
                    # else: same scheme selected — leave existing LiveMarkingScheme in place
                else:
                    old_live = workflow.scheme
                    workflow.scheme_id = None
                    if old_live is not None:
                        db.session.delete(old_live)

            workflow.notify_on_moderation_required = list(
                form.notify_on_moderation_required.data
            )
            workflow.notify_on_validation_failure = list(
                form.notify_on_validation_failure.data
            )

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

        return redirect(
            url_for("convenor.event_marking_workflows_inspector", event_id=event.id)
        )

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
        message=f"<p>Are you sure you want to permanently delete the marking workflow "
        f'<strong>"{workflow.name}"</strong>?</p>'
        f'<p class="text-danger">This will also delete all associated submitter reports '
        f"and marking reports. This action cannot be undone.</p>",
        action_url=url_for(
            "convenor.confirm_delete_marking_workflow",
            workflow_id=workflow_id,
            url=url,
            text=text,
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
        a for a in event.period.attachments.all() if a.id not in already_attached_ids
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


@convenor.route(
    "/confirm_add_workflow_attachment/<int:workflow_id>/<int:attachment_id>"
)
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
        flash(
            "This attachment does not belong to the correct submission period.", "error"
        )
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


@convenor.route("/restart_report_processing/<int:record_id>")
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def restart_report_processing(record_id):
    """Restart the report processing chain for a SubmissionRecord whose processing failed."""
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(record_id)
    pclass: ProjectClass = record.period.config.project_class

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if not record.report_processing_failed:
        flash(
            "Report processing has not failed for this submission, or no report has been uploaded.",
            "info",
        )
        return redirect(redirect_url())

    try:
        # Expire the old generated asset if present (shouldn't be, but be safe)
        if record.processed_report is not None:
            record.processed_report_id = None

        # Reset state flags so the process chain can run cleanly
        record.celery_started = False
        record.celery_finished = False
        record.celery_failed = False
        record.timestamp = None

        db.session.flush()

        # Re-dispatch the processing chain
        celery = current_app.extensions["celery"]
        process_task = celery.tasks["app.tasks.process_report.process"]
        finalize_task = celery.tasks["app.tasks.process_report.finalize"]
        error_task = celery.tasks["app.tasks.process_report.error"]

        work = celery_chain(
            process_task.si(record.id),
            finalize_task.si(record.id),
        ).on_error(error_task.si(record.id, current_user.id))

        record.celery_started = True
        log_db_commit(
            f"Restarted report processing for submission record id={record_id}",
            user=current_user,
            project_classes=pclass,
        )
        work.apply_async()

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not restart report processing due to a database error. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    flash("Report processing has been restarted.", "success")
    return redirect(redirect_url())


@convenor.route("/dispatch_marking_report/<int:report_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def dispatch_marking_report(report_id):
    """Dispatch (or re-send) the marking notification email for a single MarkingReport."""
    report: MarkingReport = MarkingReport.query.get_or_404(report_id)
    sr: SubmitterReport = report.submitter_report
    workflow: MarkingWorkflow = sr.workflow
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if not event.open or event.closed:
        flash(
            "Marking notifications can only be dispatched while the event is open.",
            "error",
        )
        return redirect(redirect_url())

    force = request.args.get("resend", "false").lower() == "true"

    deadline_str = None
    if workflow.effective_deadline is not None:
        deadline_str = workflow.effective_deadline.isoformat()

    try:
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.marking.dispatch_single_email"]
        task.apply_async(
            args=[report_id, True, 10, None, deadline_str, force],
        )
        if force:
            flash(
                f"Marking notification re-send for {report.user.name} has been queued.",
                "success",
            )
        else:
            flash(
                f"Marking notification for {report.user.name} has been queued.",
                "success",
            )
    except Exception as e:
        current_app.logger.exception(
            "Error dispatching dispatch_single_email", exc_info=e
        )
        flash(
            "Could not dispatch marking notification. Please contact a system administrator.",
            "error",
        )

    url = request.args.get(
        "url", url_for("convenor.marking_reports_inspector", workflow_id=workflow.id)
    )
    return redirect(url)


@convenor.route("/send_marking_emails_for_workflow/<int:workflow_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def send_marking_emails_for_workflow(workflow_id):
    """Dispatch marking notification emails for all undistributed MarkingReports in a workflow."""
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.closed:
        flash("Cannot send notifications for a closed marking event.", "error")
        return redirect(redirect_url())

    try:
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.marking.send_marking_emails"]
        task.apply_async(
            kwargs={
                "workflow_id": workflow_id,
                "cc_convenor": True,
                "max_attachment": 10,
                "test_user_id": None,
                "convenor_id": current_user.id,
            }
        )
        flash(
            f'Marking notifications for workflow "{workflow.name}" have been queued.',
            "success",
        )
    except Exception as e:
        current_app.logger.exception(
            "Error dispatching send_marking_emails", exc_info=e
        )
        flash(
            "Could not dispatch marking notifications. Please contact a system administrator.",
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/send_marking_emails_for_event/<int:event_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def send_marking_emails_for_event(event_id):
    """Dispatch marking notification emails for all eligible workflows in a MarkingEvent."""
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.closed:
        flash("Cannot send notifications for a closed marking event.", "error")
        return redirect(redirect_url())

    try:
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.marking.send_marking_event_emails"]
        task.apply_async(
            kwargs={
                "event_id": event_id,
                "cc_convenor": True,
                "max_attachment": 10,
                "test_user_id": None,
                "convenor_id": current_user.id,
            }
        )
        flash(
            f'Marking notifications for event "{event.name}" have been queued.',
            "success",
        )
    except Exception as e:
        current_app.logger.exception(
            "Error dispatching send_marking_event_emails", exc_info=e
        )
        flash(
            "Could not dispatch marking notifications. Please contact a system administrator.",
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/open_marking_event/<int:event_id>")
@roles_accepted("faculty", "admin", "root")
def open_marking_event(event_id):
    """Show a confirmation page for opening a MarkingEvent and distributing marking emails."""
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.closed:
        flash("Cannot open a marking event that has already been closed.", "error")
        return redirect(redirect_url())

    if event.open:
        flash("This marking event is already open.", "info")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    title = f'Open marking event "{event.name}"'
    panel_title = f"Open marking event <strong>{event.name}</strong>"
    action_url = url_for("convenor.do_open_marking_event", event_id=event_id, url=url)
    test_url = url_for("convenor.test_marking_event", event_id=event_id, url=url)
    workflow_count = event.workflows.count()
    message = (
        f"<p>Are you sure you wish to open the marking event <strong>{event.name}</strong>?</p>"
        f"<p>Marking notification emails will be dispatched for all {workflow_count} "
        f"workflow{'s' if workflow_count != 1 else ''} in this event, where reports are "
        f"already available. Further notifications can be sent later for reports uploaded "
        f"after this point.</p>"
        f"<p>To send a test distribution first, "
        f'<a href="{test_url}">click here to run a test</a>.</p>'
        f"<p>This action cannot be undone.</p>"
    )
    submit_label = "Open event and send notifications"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@convenor.route("/do_open_marking_event/<int:event_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def do_open_marking_event(event_id):
    """Set event.open = True and dispatch marking emails for all workflows."""
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.closed:
        flash("Cannot open a marking event that has already been closed.", "error")
        return redirect(redirect_url())

    if event.open:
        flash("This marking event is already open.", "info")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    event.open = True
    event.last_edit_id = current_user.id
    event.last_edit_timestamp = datetime.now()

    try:
        log_db_commit(
            f'Opened marking event "{event.name}" for period "{event.period.display_name}"',
            user=current_user,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        flash(
            "Could not open marking event due to a database error. Please contact a system administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()
        return redirect(url)

    try:
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.marking.send_marking_event_emails"]
        task.apply_async(
            kwargs={
                "event_id": event_id,
                "cc_convenor": True,
                "max_attachment": 10,
                "test_user_id": None,
                "convenor_id": current_user.id,
            }
        )
        flash(
            f'Marking event "{event.name}" has been opened and notification emails have been queued.',
            "success",
        )
    except Exception as e:
        current_app.logger.exception(
            "Error dispatching send_marking_event_emails", exc_info=e
        )
        flash(
            "Marking event was opened but notifications could not be dispatched. Please contact a system administrator.",
            "error",
        )

    return redirect(url)


@convenor.route("/test_marking_event/<int:event_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def test_marking_event(event_id):
    """Show a form to select a test recipient, then dispatch a test distribution for a MarkingEvent."""
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.closed:
        flash("Cannot send test notifications for a closed marking event.", "error")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    TestMarkingEventForm = TestMarkingEventFormFactory(pclass)
    form = TestMarkingEventForm(request.form)

    if form.validate_on_submit():
        test_user_id = form.test_target.data.id
        try:
            celery = current_app.extensions["celery"]
            task = celery.tasks["app.tasks.marking.send_marking_event_emails"]
            task.apply_async(
                kwargs={
                    "event_id": event_id,
                    "cc_convenor": True,
                    "max_attachment": 10,
                    "test_user_id": test_user_id,
                    "convenor_id": current_user.id,
                }
            )
            flash(
                f'Test notifications for marking event "{event.name}" have been queued '
                f"to {form.test_target.data.name}.",
                "success",
            )
        except Exception as e:
            current_app.logger.exception(
                "Error dispatching test send_marking_event_emails", exc_info=e
            )
            flash(
                "Could not dispatch test notifications. Please contact a system administrator.",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "convenor/markingevent/test_marking_event.html",
        event=event,
        form=form,
        url=url,
        title=f'Test notifications for "{event.name}"',
        formtitle=f"Send test notifications for marking event <strong>{event.name}</strong>",
    )


@convenor.route("/clear_marking_grade/<int:report_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def clear_marking_grade(report_id):
    """
    Clear the grade_submitted_by_id and grade_submitted_timestamp fields on a MarkingReport,
    re-opening the marking form for the assessor.
    """
    report: MarkingReport = MarkingReport.query.get_or_404(report_id)
    workflow: MarkingWorkflow = report.submitter_report.workflow
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    report.grade_submitted_by_id = None
    report.grade_submitted_timestamp = None

    try:
        log_db_commit(
            f"Cleared marking grade submission for report #{report.id} (workflow: {workflow.name})",
            user=current_user,
            project_classes=pclass,
        )
        flash(
            f"The marking form for {report.user.name} has been re-opened. "
            "The assessor can now resubmit their report.",
            "success",
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not clear marking grade due to a database error.", "error")

    url = request.args.get(
        "url", url_for("convenor.marking_reports_inspector", workflow_id=workflow.id)
    )
    return redirect(url)


@convenor.route("/marking_report_properties/<int:report_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def marking_report_properties(report_id):
    """
    Edit the editable properties of a MarkingReport (currently: weight).
    Accessible to convenors, admins, and root users.
    """
    report: MarkingReport = MarkingReport.query.get_or_404(report_id)
    workflow: MarkingWorkflow = report.submitter_report.workflow
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.marking_reports_inspector", workflow_id=workflow.id)
    )

    form = MarkingReportPropertiesForm(obj=report)

    if form.validate_on_submit():
        report.weight = form.weight.data

        try:
            log_db_commit(
                f"Updated properties for MarkingReport #{report.id} (workflow: {workflow.name}): "
                f"weight={report.weight}",
                user=current_user,
                project_classes=pclass,
            )
            flash("Marking report properties updated.", "success")
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save marking report properties due to a database error.",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "convenor/markingevent/marking_report_properties.html",
        form=form,
        report=report,
        workflow=workflow,
        pclass=pclass,
        url=url,
    )


@convenor.route("/assign-moderator/<int:submitter_report_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def assign_moderator(submitter_report_id):
    from ..models.submissions import SubmissionRoleTypesMixin
    from ..tasks.markingevent import _assign_moderator, advance_submitter_report

    sr = (
        db.session.query(SubmitterReport)
        .filter_by(id=submitter_report_id)
        .first_or_404()
    )
    workflow = sr.workflow
    pclass = workflow.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.submitter_reports_inspector", workflow_id=workflow.id)
    )

    form = AssignModeratorFormFactory(pclass.id)()

    if form.validate_on_submit():
        user = form.moderator.data
        record = sr.record

        new_role = SubmissionRole(
            submission_id=record.id,
            user_id=user.id,
            role=SubmissionRoleTypesMixin.ROLE_MODERATOR,
        )
        db.session.add(new_role)
        db.session.flush()

        _assign_moderator(sr, new_role)
        advance_submitter_report(sr)

        try:
            log_db_commit(
                f"Assigned moderator {user.name} to SubmitterReport #{sr.id} "
                f"(workflow: {workflow.name}, student: {sr.student.user.name})",
                user=current_user,
                project_classes=pclass,
            )
            flash(f"Moderator {user.name} assigned successfully.", "success")
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not assign moderator due to a database error.", "error")
            return redirect(url)

        return redirect(url)

    return render_template_context(
        "convenor/markingevent/assign_moderator.html",
        form=form,
        sr=sr,
        workflow=workflow,
        pclass=pclass,
        url=url,
    )


@convenor.route(
    "/accept-moderator-grade/<int:mod_report_id>/<int:workflow_id>", methods=["POST"]
)
@roles_accepted("faculty", "admin", "root")
def accept_moderator_grade(mod_report_id, workflow_id):
    from datetime import datetime

    from ..models.markingevent import ModeratorReport, SubmitterReportWorkflowStates

    mod_report = (
        db.session.query(ModeratorReport).filter_by(id=mod_report_id).first_or_404()
    )
    sr = mod_report.submitter_report
    workflow = sr.workflow
    pclass = workflow.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    sr.grade = mod_report.grade
    sr.grade_generated_by_id = current_user.id
    sr.grade_generated_timestamp = datetime.now()
    sr.workflow_state = SubmitterReportWorkflowStates.READY_TO_SIGN_OFF

    url = url_for("convenor.submitter_reports_inspector", workflow_id=workflow_id)

    try:
        log_db_commit(
            f"Accepted moderator grade {mod_report.grade} for SubmitterReport #{sr.id} "
            f"(workflow: {workflow.name}, student: {sr.student.user.name})",
            user=current_user,
            project_classes=pclass,
        )
        flash("Moderator grade accepted.", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not accept moderator grade due to a database error.", "error")

    return redirect(url)
