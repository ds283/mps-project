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
from datetime import datetime
from functools import partial

from celery import chain as celery_chain
from flask import current_app, flash, jsonify, redirect, request, session, url_for
from flask_login import current_user, login_required
from flask_security import roles_accepted
from sqlalchemy import and_, distinct, func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import aliased

import app.ajax as ajax

from ..database import db
from ..models import (
    EmailTemplate,
    EmailWorkflow,
    FeedbackOrchestrationJob,
    LiveMarkingScheme,
    MarkingEvent,
    MarkingReport,
    MarkingScheme,
    MarkingWorkflow,
    ModeratorReport,
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
from ..models.emails import DEFAULT_MAX_ATTACHMENT_SIZE
from ..models.markingevent import (
    _DISTRIBUTED_STATE_VALUES,
    ConflationReport,
    ConvenorAction,
    ConvenorActionButton,
    MarkingEventWorkflowStates,
    SubmitterReportWorkflowStates,
)
from ..models.similarity import SimilarityConcern
from ..models.submissions import SubmissionRoleTypesMixin
from ..shared.asset_tools import AssetUploadManager
from ..shared.context.convenor_dashboard import get_convenor_dashboard_data
from ..shared.context.global_context import render_template_context
from ..shared.forms.forms import ConfirmActionForm
from ..shared.forms.wtf_validators import (
    make_unique_marking_event_in_period,
    make_unique_marking_scheme_in_pclass,
    make_unique_marking_workflow_in_event,
    make_unique_marking_workflow_key_in_event,
    make_valid_marking_targets,
)
from ..shared.grade_rounding import ACTIVE_ROUNDING_POLICY
from ..shared.utils import redirect_url
from ..shared.validators import validate_is_convenor
from ..shared.workflow_logging import log_db_commit
from ..tasks.similarity_analysis import CHUNK_SIMILARITY_THRESHOLD
from ..tasks.thumbnails import dispatch_thumbnail_task
from ..tools.ServerSideProcessing import ServerSideSQLHandler
from . import convenor
from .forms import (
    ActionForm,
    AddMarkingEventForm,
    AddMarkingSchemeForm,
    AssignModeratorFormFactory,
    EditMarkingEventForm,
    EditMarkingSchemeForm,
    EnterTurnitinScoreForm,
    GenerateFeedbackFormFactory,
    MarkingReportPropertiesForm,
    MarkingWorkflowFormFactory,
    PushFeedbackForm,
    TestMarkingEventFormFactory,
    TestMarkingReminderFormFactory,
    build_resolve_risk_factors_form,
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


@convenor.route("/marking_event_feedback_jobs_status/<int:event_id>")
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def marking_event_feedback_jobs_status(event_id):
    """
    AJAX polling endpoint for live progress updates on FeedbackOrchestrationJob
    instances belonging to a MarkingEvent.  Used by the JS polling loop on the
    marking workflow inspector page.
    """
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.period.config.project_class
    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"], message=False
    ):
        return jsonify({"error": "Access denied"}), 403

    watched_ids_param = request.args.get("ids", "")
    watched_uuids = set(u.strip() for u in watched_ids_param.split(",") if u.strip())

    active_jobs = (
        db.session.query(FeedbackOrchestrationJob)
        .filter(
            FeedbackOrchestrationJob.event_id == event_id,
            FeedbackOrchestrationJob.status.in_(
                FeedbackOrchestrationJob.ACTIVE_STATUSES
            ),
        )
        .all()
    )

    active_uuids = {j.uuid for j in active_jobs}
    just_finished = bool(watched_uuids and not watched_uuids.issubset(active_uuids))

    jobs_data = {}
    for job in active_jobs:
        jobs_data[job.uuid] = {
            "completed": job.completed_count or 0,
            "failed": job.failed_count or 0,
            "total": job.total_count or 0,
            "elapsed_seconds": job.elapsed_seconds,
        }

    return jsonify(
        {
            "just_finished": just_finished,
            "active_count": len(active_jobs),
            "jobs": jobs_data,
        }
    )


@convenor.route("/feedback_job_pause/<string:uuid>")
@roles_accepted("faculty", "admin", "root", "convenor")
def feedback_job_pause(uuid):
    job: FeedbackOrchestrationJob = (
        db.session.query(FeedbackOrchestrationJob).filter_by(uuid=uuid).first_or_404()
    )
    event: MarkingEvent = job.event
    if event is None:
        flash("Could not determine the MarkingEvent for this job.", "error")
        return redirect(redirect_url())
    pclass = event.period.config.project_class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())
    if job.is_active:
        job.pause()
        try:
            log_db_commit(
                f"Paused FeedbackOrchestrationJob {uuid}",
                endpoint="feedback_job_pause",
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
    return redirect(
        url_for("convenor.event_marking_workflows_inspector", event_id=event.id)
    )


@convenor.route("/feedback_job_resume/<string:uuid>")
@roles_accepted("faculty", "admin", "root", "convenor")
def feedback_job_resume(uuid):
    job: FeedbackOrchestrationJob = (
        db.session.query(FeedbackOrchestrationJob).filter_by(uuid=uuid).first_or_404()
    )
    event: MarkingEvent = job.event
    if event is None:
        flash("Could not determine the MarkingEvent for this job.", "error")
        return redirect(redirect_url())
    pclass = event.period.config.project_class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())
    if job.is_active:
        job.resume()
        try:
            log_db_commit(
                f"Resumed FeedbackOrchestrationJob {uuid}",
                endpoint="feedback_job_resume",
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        # Kick the coordinator so it picks up the resumed job immediately.
        celery = current_app.extensions["celery"]
        t = celery.tasks[
            "app.tasks.feedback_orchestration.global_feedback_orchestration_step"
        ]
        t.apply_async(queue="default")
    return redirect(
        url_for("convenor.event_marking_workflows_inspector", event_id=event.id)
    )


@convenor.route("/feedback_job_cancel/<string:uuid>")
@roles_accepted("faculty", "admin", "root", "convenor")
def feedback_job_cancel(uuid):
    job: FeedbackOrchestrationJob = (
        db.session.query(FeedbackOrchestrationJob).filter_by(uuid=uuid).first_or_404()
    )
    event: MarkingEvent = job.event
    if event is None:
        flash("Could not determine the MarkingEvent for this job.", "error")
        return redirect(redirect_url())
    pclass = event.period.config.project_class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())
    if job.is_active:
        job.mark_failed()
        try:
            log_db_commit(
                f"Cancelled FeedbackOrchestrationJob {uuid}",
                endpoint="feedback_job_cancel",
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        # Dispatch coordinator so it cleans up the Redis keys.
        celery = current_app.extensions["celery"]
        t = celery.tasks[
            "app.tasks.feedback_orchestration.global_feedback_orchestration_step"
        ]
        t.apply_async(queue="default")
    return redirect(
        url_for("convenor.event_marking_workflows_inspector", event_id=event.id)
    )


@convenor.route(
    "/generate_marking_event_feedback/<int:event_id>", methods=["GET", "POST"]
)
@roles_accepted("faculty", "admin", "root", "convenor")
def generate_marking_event_feedback(event_id):
    """
    Let a convenor select a FeedbackRecipe and kick off PDF generation for a MarkingEvent.

    In READY_TO_GENERATE_FEEDBACK state, queues all ConflationReports.
    In READY_TO_PUSH_FEEDBACK state, queues only those without existing feedback ("fill missing").
    """
    from ..models.feedback import FeedbackRecipe
    from ..tasks.feedback_orchestration import launch_feedback_job

    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    allowed_states = (
        MarkingEventWorkflowStates.READY_TO_GENERATE_FEEDBACK,
        MarkingEventWorkflowStates.READY_TO_PUSH_FEEDBACK,
    )
    if event.workflow_state not in allowed_states:
        flash(
            "Feedback generation is not available for this event in its current state.",
            "warning",
        )
        return redirect(
            url_for("convenor.event_marking_workflows_inspector", event_id=event_id)
        )

    fill_missing = (
        event.workflow_state == MarkingEventWorkflowStates.READY_TO_PUSH_FEEDBACK
    )
    all_crs = event.conflation_reports.all()
    cr_count = len(all_crs)

    if fill_missing:
        pending_crs = [cr for cr in all_crs if cr.feedback_reports.count() == 0]
    else:
        pending_crs = all_crs
    pending_count = len(pending_crs)

    url = request.args.get(
        "url",
        url_for("convenor.event_marking_workflows_inspector", event_id=event_id),
    )
    text = request.args.get("text", "Marking workflows")
    title = "Fill missing feedback" if fill_missing else "Generate feedback"

    form = GenerateFeedbackFormFactory(pclass.id)()

    if form.validate_on_submit():
        recipe: FeedbackRecipe = form.recipe.data
        cr_ids = [cr.id for cr in pending_crs]

        if not cr_ids:
            flash(
                "All students already have feedback documents. Nothing to generate.",
                "info",
            )
            return redirect(
                url_for("convenor.event_marking_workflows_inspector", event_id=event_id)
            )

        try:
            launch_feedback_job(
                event=event,
                recipe=recipe,
                cr_ids=cr_ids,
                owner=current_user,
                convenor_id=current_user.id,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "A database error occurred while creating the feedback job. Please try again.",
                "error",
            )
            return redirect(
                url_for("convenor.event_marking_workflows_inspector", event_id=event_id)
            )

        plural = "s" if len(cr_ids) != 1 else ""
        flash(
            f'Queued {len(cr_ids)} feedback PDF{plural} for generation using recipe "{recipe.label}".',
            "success",
        )
        return redirect(
            url_for("convenor.event_marking_workflows_inspector", event_id=event_id)
        )

    return render_template_context(
        "convenor/feedback/generate_feedback_form.html",
        event=event,
        form=form,
        url=url,
        text=text,
        title=title,
        cr_count=cr_count,
        fill_missing=fill_missing,
        pending_count=pending_count,
    )


@convenor.route("/marking_event_conflation_reports/<int:event_id>")
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def marking_event_conflation_reports(event_id):
    """
    ConflationReport inspector for a MarkingEvent.
    Shows all ConflationReport instances with their grade summaries and feedback status.
    """
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"]
    ):
        return redirect(redirect_url())

    url = request.args.get(
        "url",
        url_for("convenor.event_marking_workflows_inspector", event_id=event_id),
    )
    text = request.args.get("text", "Marking workflows")

    feedback_jobs = (
        db.session.query(FeedbackOrchestrationJob)
        .filter(
            FeedbackOrchestrationJob.event_id == event.id,
            FeedbackOrchestrationJob.status.in_(
                FeedbackOrchestrationJob.ACTIVE_STATUSES
            ),
        )
        .order_by(FeedbackOrchestrationJob.created_at.desc())
        .all()
    )

    all_crs = event.conflation_reports.all()
    total_count = len(all_crs)
    with_feedback_count = sum(1 for cr in all_crs if cr.feedback_reports.count() > 0)
    sent_count = sum(1 for cr in all_crs if cr.feedback_sent)
    failed_count = sum(1 for cr in all_crs if cr.feedback_generation_failed)
    in_progress_count = sum(1 for cr in all_crs if cr.feedback_celery_id is not None)
    stale_count = sum(1 for cr in all_crs if cr.is_stale)

    return render_template_context(
        "convenor/markingevent/conflation_reports_inspector.html",
        event=event,
        pclass=pclass,
        url=url,
        text=text,
        feedback_jobs=feedback_jobs,
        total_count=total_count,
        with_feedback_count=with_feedback_count,
        sent_count=sent_count,
        failed_count=failed_count,
        in_progress_count=in_progress_count,
        stale_count=stale_count,
        propagate_form=ActionForm(),
        delete_all_form=ActionForm(),
        rounding_policy=ACTIVE_ROUNDING_POLICY,
    )


@convenor.route("/conflation_reports_ajax/<int:event_id>", methods=["POST"])
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def conflation_reports_ajax(event_id):
    """AJAX endpoint for ConflationReport inspector DataTable"""
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"], message=False
    ):
        return jsonify({"error": "Access denied"}), 403

    base_query = (
        db.session.query(ConflationReport)
        .join(
            SubmissionRecord,
            SubmissionRecord.id == ConflationReport.submission_record_id,
        )
        .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
        .join(StudentData, StudentData.id == SubmittingStudent.student_id)
        .join(User, User.id == StudentData.id)
        .filter(ConflationReport.marking_event_id == event_id)
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
        return handler.build_payload(
            partial(ajax.convenor.conflation_report_data, event_id)
        )


# ---------------------------------------------------------------------------
# ConflationReport individual action routes
# ---------------------------------------------------------------------------


def _conflation_report_editable(cr: ConflationReport) -> bool:
    """Return True if the ConflationReport can be edited (feedback not yet sent)."""
    return not cr.feedback_sent


def _delete_feedback_for_cr(cr: ConflationReport, audit_suffix: str = "") -> None:
    """
    Delete all FeedbackReport records (and their GeneratedAssets + physical files) attached to cr.
    Uses direct SQL DELETEs on both association tables so that missing rows (e.g. when a
    FeedbackReport was never linked to submission_record_to_feedback_report) do not raise
    StaleDataError.  Flushes after the association DELETEs so FK constraints are satisfied
    before the FeedbackReport rows themselves are deleted.
    Clears cr.recipe, cr.feedback_celery_id, and cr.feedback_generation_failed.
    Caller is responsible for db.session.commit() / rollback.
    """
    from sqlalchemy import delete as sa_delete

    import app.shared.cloud_object_store.bucket_types as buckets

    from ..models.associations import submission_record_to_feedback_report
    from ..models.markingevent import conflation_report_to_feedback_report
    from ..shared.asset_tools import AssetCloudAdapter

    reports = cr.feedback_reports.all()
    report_ids = [r.id for r in reports]

    if report_ids:
        db.session.execute(
            sa_delete(conflation_report_to_feedback_report).where(
                conflation_report_to_feedback_report.c.feedback_report_id.in_(
                    report_ids
                )
            )
        )
        db.session.execute(
            sa_delete(submission_record_to_feedback_report).where(
                submission_record_to_feedback_report.c.report_id.in_(report_ids)
            )
        )
    # Flush the association-table DELETEs before removing the FeedbackReport rows.
    db.session.flush()

    bucket_map = current_app.config.get("OBJECT_STORAGE_BUCKETS", {})
    thumbnails_store = bucket_map.get(buckets.THUMBNAILS_BUCKET)

    for report in reports:
        asset = report.asset
        db.session.delete(report)
        db.session.flush()  # ensure feedback_reports row is gone before GeneratedAsset DELETE

        if asset is not None:
            if asset.bucket in bucket_map:
                try:
                    AssetCloudAdapter(
                        asset,
                        bucket_map[asset.bucket],
                        audit_data=f"_delete_feedback_for_cr{audit_suffix}",
                    ).delete()
                except FileNotFoundError:
                    pass

            for thumb_attr in ("small_thumbnail", "medium_thumbnail"):
                thumbnail = getattr(asset, thumb_attr, None)
                if thumbnail is not None and thumbnails_store is not None:
                    try:
                        AssetCloudAdapter(
                            thumbnail,
                            thumbnails_store,
                            audit_data=f"_delete_feedback_for_cr thumbnail{audit_suffix}",
                            encryption_attr=None,
                            compressed_attr=None,
                        ).delete()
                    except FileNotFoundError:
                        pass
                    db.session.delete(thumbnail)
                    setattr(asset, f"{thumb_attr}_id", None)

            db.session.delete(asset)

    cr.recipe = None
    cr.feedback_celery_id = None
    cr.feedback_generation_failed = False


@convenor.route("/reconflate_conflation_report/<int:cr_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root", "convenor")
def reconflate_conflation_report(cr_id):
    """
    Re-run conflation for a single ConflationReport whose is_stale flag is set.
    Clears is_stale on success.
    """
    cr: ConflationReport = ConflationReport.query.get_or_404(cr_id)
    event: MarkingEvent = cr.marking_event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get(
        "url",
        url_for("convenor.marking_event_conflation_reports", event_id=event.id),
    )

    form = ActionForm(request.form)
    if not form.validate_on_submit():
        flash("Invalid request.", "error")
        return redirect(url)

    if not _conflation_report_editable(cr):
        flash(
            "Cannot reconflate: feedback has already been sent for this student.",
            "warning",
        )
        return redirect(url)

    if not cr.is_stale:
        flash(
            "This conflation report is not stale; reconflation is not needed.", "info"
        )
        return redirect(url)

    targets = event.targets_as_dict
    if not targets:
        flash("This event has no conflation targets defined.", "error")
        return redirect(url)

    workflows = event.workflows.all()
    record = cr.submission_record

    grades = {}
    for wf in workflows:
        sr = (
            db.session.query(SubmitterReport)
            .filter_by(record_id=record.id, workflow_id=wf.id)
            .first()
        )
        if sr is None or sr.grade is None:
            flash(
                f"Reconflation failed: missing grade in workflow '{wf.name}' "
                f"for student '{record.owner.student.user.name}'.",
                "error",
            )
            return redirect(url)
        grades[wf.key] = float(sr.grade)

    result = {}
    for target_name, expr in targets.items():
        try:
            value = eval(expr, {"__builtins__": {}}, grades)  # noqa: S307
            result[target_name] = ACTIVE_ROUNDING_POLICY.round(float(value))
        except Exception as exc:
            flash(
                f"Reconflation failed: error evaluating target '{target_name}' "
                f"(expression: {expr!r}): {exc}.",
                "error",
            )
            return redirect(url)

    try:
        cr.conflation_report = json.dumps(
            {
                "targets": result,
                "metadata": {"rounding_policy": ACTIVE_ROUNDING_POLICY.identifier},
            }
        )
        cr.generated_by_id = current_user.id
        cr.generated_timestamp = datetime.now()
        cr.is_stale = False
        log_db_commit(
            f"Reconflated ConflationReport for student "
            f"'{record.owner.student.user.name}' in event '{event.name}' ({pclass.name})",
            user=current_user,
            project_classes=pclass,
        )
        flash(
            f"Reconflation complete for '{record.owner.student.user.name}'.", "success"
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception(
            "SQLAlchemyError in reconflate_conflation_report", exc_info=e
        )
        flash("Could not reconflate due to a database error.", "error")

    return redirect(url)


@convenor.route("/delete_conflation_report_feedback/<int:cr_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root", "convenor")
def delete_conflation_report_feedback(cr_id):
    """
    Delete all FeedbackReport instances attached to a ConflationReport.
    If this leaves no ConflationReport in the event with any feedback, regress the event
    to READY_TO_GENERATE_FEEDBACK state.
    """
    cr: ConflationReport = ConflationReport.query.get_or_404(cr_id)
    event: MarkingEvent = cr.marking_event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get(
        "url",
        url_for("convenor.marking_event_conflation_reports", event_id=event.id),
    )

    form = ActionForm(request.form)
    if not form.validate_on_submit():
        flash("Invalid request.", "error")
        return redirect(url)

    if not _conflation_report_editable(cr):
        flash(
            "Cannot delete feedback: feedback has already been sent for this student.",
            "warning",
        )
        return redirect(url)

    if cr.feedback_reports.count() == 0:
        flash("No feedback reports to delete.", "info")
        return redirect(url)

    student_name = cr.submission_record.owner.student.user.name

    try:
        _delete_feedback_for_cr(cr, audit_suffix=f" (cr id #{cr.id})")

        # If no ConflationReport in this event now has any feedback, regress the event state
        all_crs = event.conflation_reports.all()
        any_with_feedback = any(c.feedback_reports.count() > 0 for c in all_crs)
        if (
            not any_with_feedback
            and event.workflow_state
            == MarkingEventWorkflowStates.READY_TO_PUSH_FEEDBACK
        ):
            event.workflow_state = MarkingEventWorkflowStates.READY_TO_GENERATE_FEEDBACK

        log_db_commit(
            f"Deleted feedback report(s) for student '{student_name}' "
            f"in event '{event.name}' ({pclass.name})",
            user=current_user,
            project_classes=pclass,
        )
        flash("Feedback reports deleted.", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception(
            "SQLAlchemyError in delete_conflation_report_feedback", exc_info=e
        )
        flash("Could not delete feedback due to a database error.", "error")

    return redirect(url)


@convenor.route(
    "/regenerate_conflation_report_feedback/<int:cr_id>", methods=["GET", "POST"]
)
@roles_accepted("faculty", "admin", "root", "convenor")
def regenerate_conflation_report_feedback(cr_id):
    """
    Regenerate feedback for a single ConflationReport.
    Presents the same recipe-selection form as generate_marking_event_feedback.
    """
    from ..models.feedback import FeedbackRecipe
    from ..tasks.feedback_orchestration import launch_feedback_job

    cr: ConflationReport = ConflationReport.query.get_or_404(cr_id)
    event: MarkingEvent = cr.marking_event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get(
        "url",
        url_for("convenor.marking_event_conflation_reports", event_id=event.id),
    )
    text = request.args.get("text", "Conflation reports")

    if not _conflation_report_editable(cr):
        flash(
            "Cannot regenerate feedback: feedback has already been sent for this student.",
            "warning",
        )
        return redirect(url)

    student_name = cr.submission_record.owner.student.user.name
    form = GenerateFeedbackFormFactory(pclass.id)()

    if form.validate_on_submit():
        recipe: FeedbackRecipe = form.recipe.data

        try:
            if cr.feedback_reports.count() > 0:
                _delete_feedback_for_cr(
                    cr, audit_suffix=f" (cr id #{cr.id}, regenerate)"
                )
                db.session.flush()

            launch_feedback_job(
                event=event,
                recipe=recipe,
                cr_ids=[cr.id],
                owner=current_user,
                convenor_id=current_user.id,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "A database error occurred while queuing the regeneration job.", "error"
            )
            return redirect(url)

        flash(
            f'Queued feedback regeneration for "{student_name}" using recipe "{recipe.label}".',
            "success",
        )
        return redirect(url)

    return render_template_context(
        "convenor/feedback/generate_feedback_form.html",
        event=event,
        form=form,
        url=url,
        text=text,
        title=f"Regenerate feedback for {student_name}",
        cr_count=1,
        fill_missing=False,
        pending_count=1,
    )


@convenor.route("/view_conflation_report_emails/<int:cr_id>")
@roles_accepted(
    "faculty", "admin", "root", "office", "convenor", "exam_board", "external_examiner"
)
def view_conflation_report_emails(cr_id):
    """
    List the EmailLog entries attached to a ConflationReport (feedback-push emails).
    """
    cr: ConflationReport = ConflationReport.query.get_or_404(cr_id)
    event: MarkingEvent = cr.marking_event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(
        pclass, allow_roles=["office", "external_examiner", "exam_board"]
    ):
        return redirect(redirect_url())

    url = request.args.get(
        "url",
        url_for("convenor.marking_event_conflation_reports", event_id=event.id),
    )
    text = request.args.get("text", "Conflation reports")

    emails = cr.feedback_emails.all()
    student_name = cr.submission_record.owner.student.user.name

    return render_template_context(
        "convenor/markingevent/conflation_report_emails.html",
        cr=cr,
        event=event,
        pclass=pclass,
        emails=emails,
        student_name=student_name,
        url=url,
        text=text,
    )


@convenor.route("/push_single_cr_feedback/<int:cr_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root", "convenor")
def push_single_cr_feedback(cr_id):
    """
    Dispatch feedback email for a single ConflationReport.

    GET: show PushFeedbackForm
    POST: validate and synchronously build + queue the EmailWorkflow items
    """
    cr: ConflationReport = ConflationReport.query.get_or_404(cr_id)
    event: MarkingEvent = cr.marking_event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get(
        "url",
        url_for("convenor.marking_event_conflation_reports", event_id=event.id),
    )
    text = request.args.get("text", "Conflation reports")

    if not _conflation_report_editable(cr):
        flash("Feedback has already been sent for this student.", "warning")
        return redirect(url)

    if cr.feedback_reports.count() == 0:
        flash(
            "No feedback reports exist for this student. Generate feedback first.",
            "warning",
        )
        return redirect(url)

    student_name = cr.submission_record.owner.student.user.name

    form = PushFeedbackForm(request.form)

    if form.validate_on_submit():
        from datetime import timedelta as _td

        from ..tasks.push_feedback import (
            MAX_ATTACHMENT_SIZE,
            _build_faculty_email_items_for_cr,
            _build_student_email_item,
            _build_target_roles,
        )

        delay_hours = form.delay_hours.data or 0
        test_email = form.test_email.data.strip() if form.test_email.data else None
        notify_supervisors = form.notify_supervisors.data
        notify_markers = form.notify_markers.data
        notify_moderators = form.notify_moderators.data
        defer = _td(hours=delay_hours)
        target_roles = _build_target_roles(
            notify_supervisors, notify_markers, notify_moderators
        )

        try:
            # ---- Student feedback email ----
            student_template = EmailTemplate.find_template_(
                EmailTemplate.PUSH_FEEDBACK_PUSH_TO_STUDENT, pclass=pclass
            )
            if student_template is not None:
                student_workflow = EmailWorkflow.build_(
                    name=f"Push student feedback: {pclass.name} — {student_name}",
                    template=student_template,
                    defer=defer,
                    pclasses=[pclass],
                    max_attachment_size=MAX_ATTACHMENT_SIZE,
                    creator=current_user,
                )
                db.session.add(student_workflow)
                db.session.flush()

                student_item = _build_student_email_item(
                    cr, current_user.id, defer, test_email
                )
                if student_item is not None:
                    student_item.workflow = student_workflow
                    db.session.add(student_item)

            # ---- Faculty feedback emails ----
            if target_roles:
                faculty_template = EmailTemplate.find_template_(
                    EmailTemplate.PUSH_FEEDBACK_PUSH_TO_SUPERVISOR, pclass=pclass
                ) or EmailTemplate.find_template_(
                    EmailTemplate.PUSH_FEEDBACK_PUSH_TO_MARKER, pclass=pclass
                )
                if faculty_template is not None:
                    faculty_workflow = EmailWorkflow.build_(
                        name=f"Push faculty feedback: {pclass.name} — {student_name}",
                        template=faculty_template,
                        defer=defer,
                        pclasses=[pclass],
                        max_attachment_size=MAX_ATTACHMENT_SIZE,
                        creator=current_user,
                    )
                    db.session.add(faculty_workflow)
                    db.session.flush()

                    fac_items = _build_faculty_email_items_for_cr(
                        cr, defer, test_email, target_roles
                    )
                    for item in fac_items:
                        item.workflow = faculty_workflow
                        db.session.add(item)

            log_db_commit(
                f"Queued feedback push for '{student_name}' in event '{event.name}' ({pclass.name})",
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "A database error occurred while queuing the feedback email.", "error"
            )
            return redirect(url)

        delay_desc = (
            f"in {delay_hours} hour{'s' if delay_hours != 1 else ''}"
            if delay_hours > 0
            else "immediately"
        )
        test_note = f" (test mode: {test_email})" if test_email else ""
        flash(
            f'Queued feedback email for "{student_name}", to be dispatched {delay_desc}{test_note}.',
            "success",
        )
        return redirect(url)

    return render_template_context(
        "convenor/feedback/push_feedback_form.html",
        event=event,
        pclass=pclass,
        form=form,
        url=url,
        text=text,
        unsent_count=1,
        total_count=1,
        single_student=student_name,
    )


@convenor.route("/push_marking_event_feedback/<int:event_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root", "convenor")
def push_marking_event_feedback(event_id):
    """
    Dispatch feedback emails for all unsent ConflationReports in a MarkingEvent.

    GET: show PushFeedbackForm
    POST: validate and dispatch push_marking_event_feedback_task via Celery
    """
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.workflow_state != MarkingEventWorkflowStates.READY_TO_PUSH_FEEDBACK:
        flash(
            "Feedback can only be pushed when the event is in the 'Ready to push feedback' state.",
            "warning",
        )
        return redirect(
            url_for("convenor.event_marking_workflows_inspector", event_id=event_id)
        )

    url = request.args.get(
        "url",
        url_for("convenor.marking_event_conflation_reports", event_id=event_id),
    )
    text = request.args.get("text", "Conflation reports")

    all_crs = event.conflation_reports.all()
    unsent_count = sum(1 for cr in all_crs if not cr.feedback_sent)

    form = PushFeedbackForm(request.form)

    if form.validate_on_submit():
        delay_hours = form.delay_hours.data or 0
        test_email = form.test_email.data.strip() if form.test_email.data else None
        notify_supervisors = form.notify_supervisors.data
        notify_markers = form.notify_markers.data
        notify_moderators = form.notify_moderators.data

        if unsent_count == 0:
            flash("All students have already had feedback sent. Nothing to do.", "info")
            return redirect(
                url_for("convenor.marking_event_conflation_reports", event_id=event_id)
            )

        celery = current_app.extensions["celery"]
        push_task = celery.tasks.get(
            "app.tasks.push_feedback.push_marking_event_feedback_task"
        )
        if push_task is None:
            flash(
                "Feedback push task is not registered. Please contact a system administrator.",
                "error",
            )
            return redirect(url)

        push_task.apply_async(
            args=[
                event_id,
                current_user.id,
                delay_hours,
                test_email,
                notify_supervisors,
                notify_markers,
                notify_moderators,
            ]
        )

        delay_desc = (
            f"in {delay_hours} hour{'s' if delay_hours != 1 else ''}"
            if delay_hours > 0
            else "immediately"
        )
        test_note = f" (test mode: {test_email})" if test_email else ""
        plural = "s" if unsent_count != 1 else ""
        flash(
            f"Queued feedback email{plural} for {unsent_count} student{plural}, "
            f"to be dispatched {delay_desc}{test_note}.",
            "success",
        )
        return redirect(
            url_for("convenor.marking_event_conflation_reports", event_id=event_id)
        )

    return render_template_context(
        "convenor/feedback/push_feedback_form.html",
        event=event,
        pclass=pclass,
        form=form,
        url=url,
        text=text,
        unsent_count=unsent_count,
        total_count=len(all_crs),
    )


@convenor.route(
    "/delete_all_conflation_report_feedback/<int:event_id>", methods=["POST"]
)
@roles_accepted("faculty", "admin", "root", "convenor")
def delete_all_conflation_report_feedback(event_id):
    """
    Delete all feedback reports (and their physical assets) for every unsent ConflationReport
    in a MarkingEvent.  If no feedback remains the event regresses to READY_TO_GENERATE_FEEDBACK.
    """
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get(
        "url",
        url_for("convenor.marking_event_conflation_reports", event_id=event_id),
    )

    form = ActionForm(request.form)
    if not form.validate_on_submit():
        flash("Invalid request.", "error")
        return redirect(url)

    eligible_crs = [
        cr
        for cr in event.conflation_reports.all()
        if _conflation_report_editable(cr) and cr.feedback_reports.count() > 0
    ]

    if not eligible_crs:
        flash("No unsent feedback reports found to delete.", "info")
        return redirect(url)

    try:
        for cr in eligible_crs:
            _delete_feedback_for_cr(
                cr, audit_suffix=f" (batch delete, event id #{event_id})"
            )

        all_crs = event.conflation_reports.all()
        any_with_feedback = any(c.feedback_reports.count() > 0 for c in all_crs)
        if (
            not any_with_feedback
            and event.workflow_state
            == MarkingEventWorkflowStates.READY_TO_PUSH_FEEDBACK
        ):
            event.workflow_state = MarkingEventWorkflowStates.READY_TO_GENERATE_FEEDBACK

        n = len(eligible_crs)
        plural = "s" if n != 1 else ""
        log_db_commit(
            f"Batch-deleted feedback report{plural} for {n} student{plural} "
            f"in event '{event.name}' ({pclass.name})",
            user=current_user,
            project_classes=pclass,
        )
        flash(f"Deleted feedback for {n} student{plural}.", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception(
            "SQLAlchemyError in delete_all_conflation_report_feedback", exc_info=e
        )
        flash("Could not delete feedback due to a database error.", "error")

    return redirect(url)


@convenor.route(
    "/regenerate_all_conflation_report_feedback/<int:event_id>", methods=["GET", "POST"]
)
@roles_accepted("faculty", "admin", "root", "convenor")
def regenerate_all_conflation_report_feedback(event_id):
    """
    Delete all existing unsent feedback for a MarkingEvent, then launch a batch generation
    job for all ConflationReports using a chosen FeedbackRecipe.
    """
    from ..models.feedback import FeedbackRecipe
    from ..tasks.feedback_orchestration import launch_feedback_job

    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get(
        "url",
        url_for("convenor.marking_event_conflation_reports", event_id=event_id),
    )
    text = request.args.get("text", "Conflation reports")

    all_crs = event.conflation_reports.all()
    eligible_crs = [cr for cr in all_crs if _conflation_report_editable(cr)]
    cr_count = len(eligible_crs)

    form = GenerateFeedbackFormFactory(pclass.id)()

    if form.validate_on_submit():
        recipe: FeedbackRecipe = form.recipe.data

        if not eligible_crs:
            flash("No eligible students found for feedback regeneration.", "info")
            return redirect(url)

        try:
            for cr in eligible_crs:
                if cr.feedback_reports.count() > 0:
                    _delete_feedback_for_cr(
                        cr,
                        audit_suffix=f" (batch regenerate, event id #{event_id})",
                    )
                    db.session.flush()

            cr_ids = [cr.id for cr in eligible_crs]
            launch_feedback_job(
                event=event,
                recipe=recipe,
                cr_ids=cr_ids,
                owner=current_user,
                convenor_id=current_user.id,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "A database error occurred while queuing the regeneration job.", "error"
            )
            return redirect(url)

        n = len(cr_ids)
        plural = "s" if n != 1 else ""
        flash(
            f'Queued feedback regeneration for {n} student{plural} using recipe "{recipe.label}".',
            "success",
        )
        return redirect(url)

    return render_template_context(
        "convenor/feedback/generate_feedback_form.html",
        event=event,
        form=form,
        url=url,
        text=text,
        title="Regenerate all feedback",
        cr_count=cr_count,
        fill_missing=False,
        pending_count=cr_count,
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
        "url", url_for("convenor.event_marking_workflows_inspector", event_id=event.id)
    )
    text = request.args.get("text", "Marking workflows")

    filter_state = request.args.get("filter_state")
    if filter_state is None and session.get(
        "convenor_submitter_reports_inspector_filter_state"
    ):
        filter_state = session["convenor_submitter_reports_inspector_filter_state"]
    if filter_state not in (
        "all",
        "not_ready",
        "distributable",
        "grading",
        "signoff_pending",
        "feedback_pending",
        "moderation",
        "intervention",
        "ready_signoff",
        "completed",
        "dropped",
    ):
        filter_state = "all"
    session["convenor_submitter_reports_inspector_filter_state"] = filter_state

    filter_risk = request.args.get("filter_risk")
    if filter_risk is None and session.get(
        "convenor_submitter_reports_inspector_filter_risk"
    ):
        filter_risk = session["convenor_submitter_reports_inspector_filter_risk"]
    if filter_risk not in ("all", "any_risk", "no_risk"):
        filter_risk = "all"
    session["convenor_submitter_reports_inspector_filter_risk"] = filter_risk

    filter_tolerance = request.args.get("filter_tolerance")
    if filter_tolerance is None and session.get(
        "convenor_submitter_reports_inspector_filter_tolerance"
    ):
        filter_tolerance = session[
            "convenor_submitter_reports_inspector_filter_tolerance"
        ]
    if filter_tolerance not in ("all", "out_of_tolerance", "in_tolerance"):
        filter_tolerance = "all"
    session["convenor_submitter_reports_inspector_filter_tolerance"] = filter_tolerance

    filter_grade = request.args.get("filter_grade")
    if filter_grade is None and session.get(
        "convenor_submitter_reports_inspector_filter_grade"
    ):
        filter_grade = session["convenor_submitter_reports_inspector_filter_grade"]
    if filter_grade not in ("all", "graded", "not_graded"):
        filter_grade = "all"
    session["convenor_submitter_reports_inspector_filter_grade"] = filter_grade

    filter_completion = request.args.get("filter_completion")
    if filter_completion is None and session.get(
        "convenor_submitter_reports_inspector_filter_completion"
    ):
        filter_completion = session[
            "convenor_submitter_reports_inspector_filter_completion"
        ]
    if filter_completion not in ("all", "completed", "not_completed"):
        filter_completion = "all"
    session["convenor_submitter_reports_inspector_filter_completion"] = (
        filter_completion
    )

    workflow_uses_tolerance = (
        workflow.scheme is not None and workflow.scheme.uses_tolerance
    )

    if not workflow_uses_tolerance and filter_tolerance != "all":
        filter_tolerance = "all"
        session["convenor_submitter_reports_inspector_filter_tolerance"] = "all"

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
        (SubmitterReportWorkflowStates.READY_TO_SIGN_OFF, "Ready to sign off"),
        (SubmitterReportWorkflowStates.COMPLETED, "Signed off"),
        (SubmitterReportWorkflowStates.FEEDBACK_AVAILABLE, "Feedback available"),
        (SubmitterReportWorkflowStates.DROPPED, "Withdrawn"),
    ]

    can_edit = event.workflow_state != MarkingEventWorkflowStates.CLOSED
    event_is_open = event.workflow_state >= MarkingEventWorkflowStates.OPEN

    total = workflow.submitter_reports.count()
    all_ready_to_sign_off = can_edit and (
        total > 0
        and state_counts.get(SubmitterReportWorkflowStates.READY_TO_SIGN_OFF, 0)
        == total
    )
    any_completed = (
        can_edit and state_counts.get(SubmitterReportWorkflowStates.COMPLETED, 0) > 0
    )

    # Count SRs that are genuinely ready to distribute: READY_TO_DISTRIBUTE state with at
    # least one MarkingReport not yet distributed. This excludes SRs that are stuck in
    # READY_TO_DISTRIBUTE because link_distribution_email failed to advance them after
    # all their emails were sent.
    distributable_sr_count = (
        db.session.query(func.count(distinct(SubmitterReport.id)))
        .join(MarkingReport, MarkingReport.submitter_report_id == SubmitterReport.id)
        .filter(
            SubmitterReport.workflow_id == workflow_id,
            SubmitterReport.workflow_state
            == SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE,
            ~MarkingReport.distribution_state.in_(list(_DISTRIBUTED_STATE_VALUES)),
        )
        .scalar()
        or 0
    )

    # Compute warning counts for CTA blocks
    _supervisor_role_types = frozenset(
        {
            SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
            SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
        }
    )
    wf_role = workflow.role

    multi_mr_count = 0
    if wf_role in _supervisor_role_types:
        multi_mr_count = sum(
            1 for sr in workflow.submitter_reports if sr.marking_reports.count() > 1
        )

    wrong_weight_count = 0
    if wf_role == SubmissionRoleTypesMixin.ROLE_MARKER:
        expected = float(workflow.event.period.number_markers)
        wrong_weight_count = sum(
            1
            for sr in workflow.submitter_reports
            if abs(
                sum(
                    float(mr.weight)
                    for mr in sr.marking_reports
                    if mr.weight is not None
                )
                - expected
            )
            > 0.001
        )

    is_privileged = current_user.has_role("root") or current_user.has_role("admin")
    banners = []

    if can_edit:
        if distributable_sr_count > 0:
            n = distributable_sr_count
            if event_is_open:
                banners.append(
                    ConvenorAction(
                        severity="danger",
                        icon="paper-plane",
                        title=f"{n} report{'s' if n != 1 else ''} ready to distribute",
                        description="Distribution emails have not been sent yet. Assessors cannot begin marking until notified.",
                        buttons=[
                            ConvenorActionButton(
                                label="View reports",
                                outline=True,
                                icon="search",
                                url=url_for(
                                    "convenor.submitter_reports_inspector",
                                    workflow_id=workflow_id,
                                    filter_state="distributable",
                                    filter_risk=filter_risk,
                                    filter_tolerance=filter_tolerance,
                                    filter_grade=filter_grade,
                                    filter_completion=filter_completion,
                                ),
                            ),
                            ConvenorActionButton(
                                label="Distribute all",
                                icon="paper-plane",
                                method="POST",
                                url=url_for(
                                    "convenor.send_marking_emails_for_workflow",
                                    workflow_id=workflow_id,
                                ),
                            ),
                        ],
                    )
                )
            else:
                banners.append(
                    ConvenorAction(
                        severity="secondary",
                        icon="lock",
                        title="Marking event has not been opened",
                        description=f"{n} submitter report{'s' if n != 1 else ''} {'are' if n != 1 else 'is'} ready to distribute, but distribution is not available until the event is opened.",
                        buttons=[
                            ConvenorActionButton(
                                label="Go to event...",
                                icon="play",
                                url=url_for(
                                    "convenor.event_marking_workflows_inspector",
                                    event_id=event.id,
                                ),
                            ),
                        ],
                    )
                )

        if workflow.has_reminder_eligible_reports:
            banners.append(
                ConvenorAction(
                    severity="warning",
                    icon="bell",
                    title="Reminder emails can be sent",
                    description="One or more marking reports are distributed but not yet submitted.",
                    buttons=[
                        ConvenorActionButton(
                            label="View reports",
                            outline=True,
                            icon="search",
                            url=url_for(
                                "convenor.submitter_reports_inspector",
                                workflow_id=workflow_id,
                                filter_state="grading",
                                filter_risk=filter_risk,
                                filter_tolerance=filter_tolerance,
                                filter_grade=filter_grade,
                                filter_completion=filter_completion,
                            ),
                        ),
                        ConvenorActionButton(
                            label="Send reminders…",
                            icon="bell",
                            url=url_for(
                                "convenor.send_reminder_for_workflow",
                                workflow_id=workflow_id,
                                url=request.url,
                                text="Submitter reports",
                            ),
                        ),
                    ],
                )
            )

        needs_moderator = state_counts.get(
            SubmitterReportWorkflowStates.NEEDS_MODERATOR_ASSIGNED, 0
        )
        if needs_moderator > 0:
            n = needs_moderator
            banners.append(
                ConvenorAction(
                    severity="danger",
                    icon="exclamation-circle",
                    title=f"{n} report{'s' if n != 1 else ''} need{'s' if n == 1 else ''} a moderator assigned",
                    description="These reports cannot proceed until a moderator is assigned.",
                    buttons=[
                        ConvenorActionButton(
                            label="Review",
                            outline=True,
                            icon="search",
                            url=url_for(
                                "convenor.submitter_reports_inspector",
                                workflow_id=workflow_id,
                                filter_state="intervention",
                                filter_risk=filter_risk,
                                filter_tolerance="out_of_tolerance",
                                filter_grade=filter_grade,
                                filter_completion=filter_completion,
                            ),
                        )
                    ],
                )
            )

        needs_intervention = state_counts.get(
            SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION, 0
        )
        if needs_intervention > 0:
            n = needs_intervention
            banners.append(
                ConvenorAction(
                    severity="danger",
                    icon="exclamation-circle",
                    title=f"{n} report{'s' if n != 1 else ''} require{'s' if n == 1 else ''} convenor intervention",
                    description="Marking cannot proceed until the convenor reviews these reports.",
                    buttons=[
                        ConvenorActionButton(
                            label="Review",
                            outline=True,
                            icon="search",
                            url=url_for(
                                "convenor.submitter_reports_inspector",
                                workflow_id=workflow_id,
                                filter_state="intervention",
                                filter_risk=filter_risk,
                                filter_tolerance=filter_tolerance,
                                filter_grade=filter_grade,
                                filter_completion=filter_completion,
                            ),
                        )
                    ],
                )
            )

        if all_ready_to_sign_off:
            banners.append(
                ConvenorAction(
                    severity="success",
                    icon="check-circle",
                    title="All reports are ready to be signed off.",
                    description="Click to sign off all reports.",
                    buttons=[
                        ConvenorActionButton(
                            label="Review",
                            outline=True,
                            icon="search",
                            url=url_for(
                                "convenor.submitter_reports_inspector",
                                workflow_id=workflow_id,
                                filter_state="ready_signoff",
                                filter_risk=filter_risk,
                                filter_tolerance=filter_tolerance,
                                filter_grade=filter_grade,
                                filter_completion=filter_completion,
                            ),
                        ),
                        ConvenorActionButton(
                            label="Sign off all",
                            icon="check-double",
                            method="POST",
                            url=url_for(
                                "convenor.complete_all_submitter_reports",
                                workflow_id=workflow_id,
                            ),
                        ),
                    ],
                )
            )

    if multi_mr_count > 0:
        n = multi_mr_count
        banners.append(
            ConvenorAction(
                severity="danger",
                icon="exclamation-triangle",
                title=f"{n} record{'s' if n != 1 else ''} {'have' if n != 1 else 'has'} more than one supervisor marking report assigned.",
                description="Each supervisor workflow record should have exactly one marking report. Please review the highlighted rows and remove duplicate assignments.",
            )
        )

    if wrong_weight_count > 0:
        n = wrong_weight_count
        banners.append(
            ConvenorAction(
                severity="danger",
                icon="exclamation-triangle",
                title=f"{n} record{'s' if n != 1 else ''} {'have' if n != 1 else 'has'} marker weights that do not sum to the expected value ({workflow.event.period.number_markers}).",
                description="Please review the highlighted rows and correct the marker assignments.",
            )
        )

    if is_privileged and any_completed:
        completed_count = state_counts.get(SubmitterReportWorkflowStates.COMPLETED, 0)
        banners.append(
            ConvenorAction(
                severity="danger",
                icon="undo",
                title="Return all completed reports to convenor",
                description=f"{completed_count} completed report{'s' if completed_count != 1 else ''} can be returned for re-editing.",
                buttons=[
                    ConvenorActionButton(
                        label="Return all…",
                        outline=True,
                        icon="undo",
                        method="POST",
                        url=url_for(
                            "convenor.return_all_submitter_reports",
                            workflow_id=workflow_id,
                        ),
                    )
                ],
            )
        )

    return render_template_context(
        "convenor/markingevent/submitter_reports_inspector.html",
        workflow=workflow,
        event=event,
        pclass=pclass,
        url=url,
        text=text,
        can_edit=can_edit,
        state_counts=state_counts,
        state_labels=state_labels,
        banners=banners,
        form=ActionForm(),
        filter_state=filter_state,
        filter_risk=filter_risk,
        filter_tolerance=filter_tolerance,
        filter_grade=filter_grade,
        filter_completion=filter_completion,
        workflow_uses_tolerance=workflow_uses_tolerance,
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

    filter_state = request.args.get("filter_state", "all")
    filter_risk = request.args.get("filter_risk", "all")
    filter_tolerance = request.args.get("filter_tolerance", "all")
    filter_grade = request.args.get("filter_grade", "all")
    filter_completion = request.args.get("filter_completion", "all")

    workflow_uses_tolerance = (
        workflow.scheme is not None and workflow.scheme.uses_tolerance
    )
    if not workflow_uses_tolerance:
        filter_tolerance = "all"

    base_query = (
        db.session.query(SubmitterReport)
        .join(SubmissionRecord, SubmissionRecord.id == SubmitterReport.record_id)
        .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
        .join(StudentData, StudentData.id == SubmittingStudent.student_id)
        .join(User, User.id == StudentData.id)
        .filter(SubmitterReport.workflow_id == workflow_id)
    )

    S = SubmitterReportWorkflowStates

    # feedback_pending is cross-state: any SR with an incomplete MarkingReport
    if filter_state == "feedback_pending":
        base_query = base_query.filter(
            SubmitterReport.marking_reports.any(
                or_(
                    MarkingReport.report_submitted.is_(False),
                    MarkingReport.feedback_submitted.is_(False),
                )
            )
        )
    else:
        # "moderation" = moderator already assigned and working (AWAITING_MODERATOR_REPORT only).
        # "intervention" = convenor must act immediately: covers both REQUIRES_CONVENOR_INTERVENTION
        # and NEEDS_MODERATOR_ASSIGNED (moderator not yet assigned; blocks workflow progress).
        _state_map = {
            "not_ready": [S.NOT_READY],
            "distributable": [S.READY_TO_DISTRIBUTE],
            "grading": [S.AWAITING_GRADING_REPORTS],
            "signoff_pending": [S.AWAITING_RESPONSIBLE_SUPERVISOR_SIGNOFF],
            "moderation": [S.AWAITING_MODERATOR_REPORT],
            "intervention": [
                S.REQUIRES_CONVENOR_INTERVENTION,
                S.NEEDS_MODERATOR_ASSIGNED,
            ],
            "ready_signoff": [S.READY_TO_SIGN_OFF],
            "completed": [S.COMPLETED, S.FEEDBACK_AVAILABLE],
            "dropped": [S.DROPPED],
        }
        if filter_state != "all" and filter_state in _state_map:
            states = _state_map[filter_state]
            if len(states) == 1:
                base_query = base_query.filter(
                    SubmitterReport.workflow_state == states[0]
                )
            else:
                base_query = base_query.filter(
                    SubmitterReport.workflow_state.in_(states)
                )

    if filter_tolerance == "out_of_tolerance":
        base_query = base_query.filter(SubmitterReport.out_of_tolerance.is_(True))
    elif filter_tolerance == "in_tolerance":
        base_query = base_query.filter(SubmitterReport.out_of_tolerance.is_(False))

    if filter_grade == "graded":
        base_query = base_query.filter(SubmitterReport.grade.isnot(None))
    elif filter_grade == "not_graded":
        base_query = base_query.filter(SubmitterReport.grade.is_(None))

    if filter_completion == "completed":
        base_query = base_query.filter(SubmitterReport.completed_by_id.isnot(None))
    elif filter_completion == "not_completed":
        base_query = base_query.filter(SubmitterReport.completed_by_id.is_(None))

    if filter_risk in ("any_risk", "no_risk"):
        _risk_types = [
            "turnitin",
            "ai_compliance",
            "ai_use",
            "document_length",
            "word_count_discrepancy",
            "similarity_flagged",
            "similarity_chunking_failed",
        ]

        def _risk_unresolved_clause(risk_type):
            # COALESCE turns NULL (path absent or risk_factors IS NULL) into 0,
            # ensuring ~or_(...) correctly includes null-risk-factor rows in "no_risk".
            present = func.coalesce(
                func.json_contains(
                    SubmissionRecord.risk_factors, '{"present": true}', f"$.{risk_type}"
                ),
                0,
            )
            resolved_true = func.coalesce(
                func.json_contains(
                    SubmissionRecord.risk_factors,
                    '{"resolved": true}',
                    f"$.{risk_type}",
                ),
                0,
            )
            return and_(present == 1, resolved_true == 0)

        risk_condition = or_(*[_risk_unresolved_clause(rt) for rt in _risk_types])
        if filter_risk == "any_risk":
            base_query = base_query.filter(risk_condition)
        else:
            base_query = base_query.filter(~risk_condition)

    student_col = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "search_collation": "utf8_general_ci",
        "order": [User.last_name, User.first_name],
    }

    faculty_name_col = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "search_collation": "utf8_general_ci",
    }

    def _marker_name_collection(search_expr):
        return SubmitterReport.marking_reports.any(
            MarkingReport.role.has(SubmissionRole.user.has(search_expr))
        )

    def _moderator_name_collection(search_expr):
        return SubmitterReport.moderator_reports.any(
            ModeratorReport.role.has(SubmissionRole.user.has(search_expr))
        )

    columns = {
        "student": student_col,
        "_marker_names": {
            **faculty_name_col,
            "search_collection": _marker_name_collection,
        },
        "_moderator_names": {
            **faculty_name_col,
            "search_collection": _moderator_name_collection,
        },
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.convenor.submitter_report_data)


@convenor.route("/resolve_turnitin/<int:submitter_report_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def resolve_turnitin_issue(submitter_report_id):
    """
    Redirect to the new resolve_risk_factors view.
    This route is retained for URL compatibility but the feature has been superseded.
    """
    sr: SubmitterReport = SubmitterReport.query.get_or_404(submitter_report_id)
    url = request.args.get("url", None)
    text = request.args.get("text", "Submitter reports")
    kwargs = {"record_id": sr.record_id, "text": text}
    if url:
        kwargs["url"] = url
    return redirect(url_for("convenor.resolve_risk_factors", **kwargs))


@convenor.route("/resolve-risk-factors/<int:record_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def resolve_risk_factors(record_id):
    """
    Display and resolve risk factors for a SubmissionRecord.

    GET:  Show a form listing all present risk factors with resolution checkboxes and annotation fields.
    POST: Record resolution for each checked factor, then re-evaluate SubmitterReport lifecycle states.
    """
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(record_id)
    period: SubmissionPeriodRecord = record.period
    pclass: ProjectClass = period.config.project_class

    if not validate_is_convenor(pclass, allow_roles=["office"]):
        return redirect(redirect_url())

    url = request.args.get(
        "url",
        url_for("convenor.marking_events_inspector", pclass_id=pclass.id),
    )
    text = request.args.get("text", "Back")

    is_retired = record.owner.retired if record.owner is not None else False

    if is_retired and request.method == "POST":
        flash(
            "Risk factors are locked for retired students and cannot be modified.",
            "warning",
        )
        return redirect(url)

    FormClass = build_resolve_risk_factors_form()
    form = FormClass(request.form)

    if form.validate_on_submit():
        try:
            # Process each risk factor type: resolve if the corresponding checkbox is checked
            for factor_type in SubmissionRecord.ALL_RISK_TYPES:
                if getattr(form, f"resolve_{factor_type}").data:
                    annotation = (
                        getattr(form, f"annotation_{factor_type}").data or ""
                    ).strip() or None
                    record.resolve_risk_factor(factor_type, current_user, annotation)

            log_db_commit(
                f"Convenor resolved risk factors for SubmissionRecord id={record_id} "
                f"(student: {record.owner.student.user.name if record.owner else 'unknown'})",
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError in resolve_risk_factors", exc_info=e
            )
            flash("A database error occurred. Please try again.", "danger")
            return redirect(url)

        # Re-evaluate SubmitterReport lifecycle states for this record
        celery = current_app.extensions["celery"]
        advance_wf = celery.tasks["app.tasks.markingevent.advance_marking_workflow"]
        advance_wf.apply_async(args=[record_id])

        flash("Risk factor resolutions recorded successfully.", "success")
        remaining = record.risk_factor_display_items()
        if any(not item["resolved"] for item in remaining):
            return redirect(
                url_for(
                    "convenor.resolve_risk_factors",
                    record_id=record_id,
                    url=url,
                    text=text,
                )
            )
        return redirect(url)

    # Prepare display items (all logic in Python, template is purely presentational)
    display_items = record.risk_factor_display_items()

    # Collect open similarity concerns for the similarity_flagged risk factor card
    sim_factor = (record.risk_factors_data or {}).get(
        SubmissionRecord.RISK_SIMILARITY_FLAGGED, {}
    )
    similarity_open_concerns = []
    if sim_factor.get("present", False):
        similarity_open_concerns = (
            db.session.query(SimilarityConcern)
            .filter(
                db.or_(
                    SimilarityConcern.record_a_id == record.id,
                    SimilarityConcern.record_b_id == record.id,
                ),
                SimilarityConcern.reviewed == db.false(),
            )
            .order_by(SimilarityConcern.transformer_cosine.desc())
            .all()
        )

    chunking_factor = (record.risk_factors_data or {}).get(
        SubmissionRecord.RISK_SIMILARITY_CHUNKING_FAILED, {}
    )

    return render_template_context(
        "convenor/markingevent/resolve_risk_factors.html",
        record=record,
        period=period,
        pclass=pclass,
        display_items=display_items,
        is_retired=is_retired,
        url=url,
        text=text,
        form=form,
        sim_factor=sim_factor,
        similarity_open_concerns=similarity_open_concerns,
        chunking_factor=chunking_factor,
        chunk_thresholds=CHUNK_SIMILARITY_THRESHOLD,
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

        # Recompute risk factors now that the Turnitin score has changed.
        record.compute_risk_factors(period.config)
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError committing risk factors in enter_turnitin_score",
                exc_info=e,
            )

        # Re-evaluate all SubmitterReport lifecycle states for this record.
        celery = current_app.extensions["celery"]
        advance_wf = celery.tasks["app.tasks.markingevent.advance_marking_workflow"]
        advance_wf.apply_async(args=[record_id])

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
        "url", url_for("convenor.event_marking_workflows_inspector", event_id=event.id)
    )
    text = request.args.get("text", "Marking workflows")

    filter_dist = request.args.get("filter_dist")
    if filter_dist is None and session.get(
        "convenor_marking_reports_inspector_filter_dist"
    ):
        filter_dist = session["convenor_marking_reports_inspector_filter_dist"]
    if filter_dist not in ("all", "distributable", "distributed", "not_distributed"):
        filter_dist = "all"
    session["convenor_marking_reports_inspector_filter_dist"] = filter_dist

    filter_sub = request.args.get("filter_sub")
    if filter_sub is None and session.get(
        "convenor_marking_reports_inspector_filter_sub"
    ):
        filter_sub = session["convenor_marking_reports_inspector_filter_sub"]
    if filter_sub not in ("all", "submitted", "awaiting", "not_submitted"):
        filter_sub = "all"
    session["convenor_marking_reports_inspector_filter_sub"] = filter_sub

    filter_fb = request.args.get("filter_fb")
    if filter_fb is None and session.get(
        "convenor_marking_reports_inspector_filter_fb"
    ):
        filter_fb = session["convenor_marking_reports_inspector_filter_fb"]
    if filter_fb not in ("all", "submitted", "pending", "not_submitted"):
        filter_fb = "all"
    session["convenor_marking_reports_inspector_filter_fb"] = filter_fb

    filter_ready = request.args.get("filter_ready")
    if filter_ready is None and session.get(
        "convenor_marking_reports_inspector_filter_ready"
    ):
        filter_ready = session["convenor_marking_reports_inspector_filter_ready"]
    if filter_ready not in ("all", "ready", "not_ready"):
        filter_ready = "all"
    session["convenor_marking_reports_inspector_filter_ready"] = filter_ready

    filter_signoff = request.args.get("filter_signoff")
    if filter_signoff is None and session.get(
        "convenor_marking_reports_inspector_filter_signoff"
    ):
        filter_signoff = session["convenor_marking_reports_inspector_filter_signoff"]
    if filter_signoff not in ("all", "signed_off", "awaiting_signoff"):
        filter_signoff = "all"
    session["convenor_marking_reports_inspector_filter_signoff"] = filter_signoff

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

    distributable_count = (
        db.session.query(func.count(MarkingReport.id))
        .join(SubmitterReport, SubmitterReport.id == MarkingReport.submitter_report_id)
        .filter(
            SubmitterReport.workflow_id == workflow_id,
            ~MarkingReport.distribution_state.in_(list(_DISTRIBUTED_STATE_VALUES)),
            SubmitterReport.workflow_state
            == SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE,
        )
        .scalar()
        or 0
    )

    signed_off_count = (
        db.session.query(func.count(MarkingReport.id))
        .join(SubmitterReport, SubmitterReport.id == MarkingReport.submitter_report_id)
        .filter(
            SubmitterReport.workflow_id == workflow_id,
            MarkingReport.signed_off_id.isnot(None),
        )
        .scalar()
        or 0
    )

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

    can_edit = event.workflow_state != MarkingEventWorkflowStates.CLOSED
    event_is_open = event.workflow_state >= MarkingEventWorkflowStates.OPEN
    banners = []

    if can_edit:
        if distributable_count > 0:
            n = distributable_count
            if event_is_open:
                banners.append(
                    ConvenorAction(
                        severity="danger",
                        icon="paper-plane",
                        title=f"{n} marking report{'s' if n != 1 else ''} ready to distribute",
                        description="Distribution emails have not been sent yet. Assessors cannot begin marking until notified.",
                        buttons=[
                            ConvenorActionButton(
                                label="View reports",
                                outline=True,
                                icon="search",
                                url=url_for(
                                    "convenor.marking_reports_inspector",
                                    workflow_id=workflow_id,
                                    filter_dist="distributable",
                                    filter_sub=filter_sub,
                                    filter_fb=filter_fb,
                                    filter_ready=filter_ready,
                                    filter_signoff=filter_signoff,
                                ),
                            ),
                            ConvenorActionButton(
                                label="Distribute all",
                                icon="paper-plane",
                                method="POST",
                                url=url_for(
                                    "convenor.send_marking_emails_for_workflow",
                                    workflow_id=workflow_id,
                                ),
                            ),
                        ],
                    )
                )
            else:
                banners.append(
                    ConvenorAction(
                        severity="secondary",
                        icon="lock",
                        title="Marking event has not been opened",
                        description=f"{n} marking report{'s' if n != 1 else ''} {'are' if n != 1 else 'is'} ready to distribute, but distribution is not available until the event is opened.",
                        buttons=[
                            ConvenorActionButton(
                                label="Go to event...",
                                icon="play",
                                url=url_for(
                                    "convenor.event_marking_workflows_inspector",
                                    event_id=event.id,
                                ),
                            ),
                        ],
                    )
                )

        if workflow.has_reminder_eligible_reports:
            banners.append(
                ConvenorAction(
                    severity="warning",
                    icon="bell",
                    title="Reminder emails can be sent",
                    description="One or more marking reports are distributed but not yet submitted.",
                    buttons=[
                        ConvenorActionButton(
                            label="View reports",
                            outline=True,
                            icon="search",
                            url=url_for(
                                "convenor.marking_reports_inspector",
                                workflow_id=workflow_id,
                                filter_dist=filter_dist,
                                filter_sub="awaiting",
                                filter_fb=filter_fb,
                                filter_ready=filter_ready,
                                filter_signoff=filter_signoff,
                            ),
                        ),
                        ConvenorActionButton(
                            label="Send reminders…",
                            icon="bell",
                            url=url_for(
                                "convenor.send_reminder_for_workflow",
                                workflow_id=workflow_id,
                                url=request.url,
                                text="Marking reports",
                            ),
                        ),
                    ],
                )
            )

    dropped_count = (
        db.session.query(func.count(MarkingReport.id))
        .join(SubmitterReport, SubmitterReport.id == MarkingReport.submitter_report_id)
        .filter(
            SubmitterReport.workflow_id == workflow_id,
            SubmitterReport.workflow_state == SubmitterReportWorkflowStates.DROPPED,
        )
        .scalar()
        or 0
    )

    return render_template_context(
        "convenor/markingevent/marking_reports_inspector.html",
        workflow=workflow,
        event=event,
        pclass=pclass,
        url=url,
        text=text,
        total_reports=total_reports,
        distributed_count=distributed_count,
        distributable_count=distributable_count,
        submitted_count=submitted_count,
        feedback_count=feedback_count,
        signed_off_count=signed_off_count,
        dropped_count=dropped_count,
        can_edit=can_edit,
        banners=banners,
        form=ActionForm(),
        web_validation_failures=web_validation_failures,
        filter_dist=filter_dist,
        filter_sub=filter_sub,
        filter_fb=filter_fb,
        filter_ready=filter_ready,
        filter_signoff=filter_signoff,
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

    filter_dist = request.args.get("filter_dist", "all")
    filter_sub = request.args.get("filter_sub", "all")
    filter_fb = request.args.get("filter_fb", "all")
    filter_ready = request.args.get("filter_ready", "all")
    filter_signoff = request.args.get("filter_signoff", "all")

    StudentUser = aliased(User)

    base_query = (
        db.session.query(MarkingReport)
        .join(SubmitterReport, SubmitterReport.id == MarkingReport.submitter_report_id)
        .join(SubmissionRecord, SubmissionRecord.id == SubmitterReport.record_id)
        .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
        .join(StudentData, StudentData.id == SubmittingStudent.student_id)
        .join(StudentUser, StudentUser.id == StudentData.id)
        .join(SubmissionRole, SubmissionRole.id == MarkingReport.role_id)
        .join(User, User.id == SubmissionRole.user_id)
        .filter(SubmitterReport.workflow_id == workflow_id)
    )

    if filter_dist == "distributable":
        base_query = base_query.filter(
            and_(
                ~MarkingReport.distribution_state.in_(list(_DISTRIBUTED_STATE_VALUES)),
                SubmitterReport.workflow_state
                == SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE,
            )
        )
    elif filter_dist == "distributed":
        base_query = base_query.filter(
            MarkingReport.distribution_state.in_(list(_DISTRIBUTED_STATE_VALUES))
        )
    elif filter_dist == "not_distributed":
        base_query = base_query.filter(
            ~MarkingReport.distribution_state.in_(list(_DISTRIBUTED_STATE_VALUES))
        )

    if filter_sub == "submitted":
        base_query = base_query.filter(MarkingReport.report_submitted.is_(True))
    elif filter_sub == "awaiting":
        base_query = base_query.filter(
            and_(
                MarkingReport.distribution_state.in_(list(_DISTRIBUTED_STATE_VALUES)),
                MarkingReport.report_submitted.is_(False),
            )
        )
    elif filter_sub == "not_submitted":
        base_query = base_query.filter(MarkingReport.report_submitted.is_(False))

    if filter_fb == "submitted":
        base_query = base_query.filter(MarkingReport.feedback_submitted.is_(True))
    elif filter_fb == "pending":
        base_query = base_query.filter(
            and_(
                MarkingReport.report_submitted.is_(True),
                MarkingReport.feedback_submitted.is_(False),
            )
        )
    elif filter_fb == "not_submitted":
        base_query = base_query.filter(MarkingReport.feedback_submitted.is_(False))

    if filter_ready == "ready":
        base_query = base_query.filter(
            SubmitterReport.workflow_state != SubmitterReportWorkflowStates.NOT_READY
        )
    elif filter_ready == "not_ready":
        base_query = base_query.filter(
            SubmitterReport.workflow_state == SubmitterReportWorkflowStates.NOT_READY
        )

    if filter_signoff == "signed_off":
        base_query = base_query.filter(MarkingReport.signed_off_id.isnot(None))
    elif filter_signoff == "awaiting_signoff":
        base_query = base_query.filter(MarkingReport.signed_off_id.is_(None))

    marker_col = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "search_collation": "utf8_general_ci",
        "order": [User.last_name, User.first_name],
    }

    student_col = {
        "search": func.concat(StudentUser.first_name, " ", StudentUser.last_name),
        "search_collation": "utf8_general_ci",
        "order": [StudentUser.last_name, StudentUser.first_name],
    }

    columns = {
        "marker": marker_col,
        "student": student_col,
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

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/markingevent/marking_schemes_inspector.html",
        pclass=pclass,
        config=config,
        convenor_data=data,
        url=url,
        text=text,
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

    if form.validate_on_submit(
        extra_validators={"name": [make_unique_marking_scheme_in_pclass(pclass_id)]}
    ):
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

    if form.validate_on_submit(
        extra_validators={
            "name": [
                make_unique_marking_scheme_in_pclass(
                    pclass.id, name=scheme.name, exclude_id=scheme.id
                )
            ]
        }
    ):
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

    if form.validate_on_submit(
        extra_validators={"name": [make_unique_marking_event_in_period(period_id)]}
    ):
        event = MarkingEvent(
            period_id=period_id,
            name=form.name.data,
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

    if form.validate_on_submit(
        extra_validators={
            "name": [
                make_unique_marking_event_in_period(
                    period.id, name=event.name, exclude_id=event.id
                )
            ],
            "targets": [make_valid_marking_targets(fiducial)],
        }
    ):
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

    form = ConfirmActionForm()
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
        form=form,
    )


@convenor.route("/confirm_delete_marking_event/<int:event_id>", methods=["POST"])
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

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("This marking event is already closed.", "info")
        return redirect(redirect_url())

    url = request.args.get(
        "url",
        url_for("convenor.period_marking_events_inspector", period_id=event.period_id),
    )
    text = request.args.get("text", "Marking events")

    form = ConfirmActionForm()
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
        form=form,
    )


@convenor.route("/close_marking_event/<int:event_id>", methods=["POST"])
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

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("This marking event is already closed.", "info")
        return redirect(url)

    try:
        event.workflow_state = MarkingEventWorkflowStates.CLOSED
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

    can_edit = event.workflow_state != MarkingEventWorkflowStates.CLOSED

    send_emails_url = url_for(
        "convenor.send_marking_emails_for_event", event_id=event_id
    )
    open_event_url = (
        url_for("convenor.open_marking_event", event_id=event_id)
        if event.workflow_state == MarkingEventWorkflowStates.WAITING
        else None
    )
    generate_feedback_url = (
        url_for("convenor.generate_marking_event_feedback", event_id=event_id)
        if event.workflow_state
        in (
            MarkingEventWorkflowStates.READY_TO_GENERATE_FEEDBACK,
            MarkingEventWorkflowStates.READY_TO_PUSH_FEEDBACK,
        )
        else None
    )
    conflation_url = (
        url_for("convenor.calculate_conflation", event_id=event_id)
        if event.workflow_state == MarkingEventWorkflowStates.READY_TO_CONFLATE
        else None
    )
    actions = event.get_convenor_actions(
        open_event_url=open_event_url,
        conflation_url=conflation_url,
        generate_feedback_url=generate_feedback_url,
        send_emails_url=send_emails_url,
    )

    # Add per-workflow CTAs.  Computed here (not in the model) so that url_for() can be called
    # without introducing routing knowledge into the model layer.
    is_privileged = current_user.has_role("root") or current_user.has_role("admin")
    if event.workflow_state != MarkingEventWorkflowStates.CLOSED:
        for workflow in event.workflows:
            workflow_url = url_for(
                "convenor.submitter_reports_inspector",
                workflow_id=workflow.id,
                url=url_for(
                    "convenor.event_marking_workflows_inspector", event_id=event_id
                ),
                text="Marking workflows",
            )

            # CTA for unresolved risk factors
            unresolved = (
                db.session.query(SubmitterReport)
                .join(
                    SubmissionRecord, SubmissionRecord.id == SubmitterReport.record_id
                )
                .filter(
                    SubmitterReport.workflow_id == workflow.id,
                    SubmitterReport.workflow_state
                    == SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION,
                )
                .count()
            )
            if unresolved > 0:
                n = unresolved
                risk_url = url_for(
                    "convenor.submitter_reports_inspector",
                    workflow_id=workflow.id,
                    filter_state="intervention",
                    filter_risk="any_risk",
                    url=url_for(
                        "convenor.event_marking_workflows_inspector", event_id=event_id
                    ),
                    text="Marking workflows",
                )
                actions.append(
                    ConvenorAction(
                        severity="warning",
                        icon="exclamation-circle",
                        title=f"Risk factors require review: {workflow.name}",
                        description=(
                            f"{n} submitter report{'s' if n != 1 else ''} in this workflow "
                            f"{'have' if n != 1 else 'has'} unresolved risk factors "
                            f"and require{'s' if n == 1 else ''} convenor review before marking "
                            f"can proceed."
                        ),
                        buttons=[
                            ConvenorActionButton(
                                label="Review risk factors",
                                url=risk_url,
                                outline=True,
                                icon="search",
                            )
                        ],
                    )
                )

            # CTA for reports awaiting moderator assignment
            needs_mod = sum(
                1
                for sr in workflow.submitter_reports
                if sr.workflow_state
                == SubmitterReportWorkflowStates.NEEDS_MODERATOR_ASSIGNED
            )
            if needs_mod > 0:
                n = needs_mod
                mod_url = url_for(
                    "convenor.submitter_reports_inspector",
                    workflow_id=workflow.id,
                    filter_state="intervention",
                    filter_tolerance="out_of_tolerance",
                    url=url_for(
                        "convenor.event_marking_workflows_inspector", event_id=event_id
                    ),
                    text="Marking workflows",
                )
                actions.append(
                    ConvenorAction(
                        severity="danger",
                        icon="exclamation-circle",
                        title=f"Moderator{'s' if n != 1 else ''} need assigning: {workflow.name}",
                        description=(
                            f"{n} report{'s' if n != 1 else ''} in this workflow "
                            f"cannot proceed until a moderator is assigned."
                        ),
                        buttons=[
                            ConvenorActionButton(
                                label="Review reports",
                                url=mod_url,
                                outline=True,
                                icon="search",
                            )
                        ],
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
                        icon="exclamation-circle",
                        title=f"Missing Turnitin data: {workflow.name}",
                        description=(
                            f"{n} submitter report{'s' if n != 1 else ''} in this workflow "
                            f"{'are' if n != 1 else 'is'} missing Turnitin similarity data. "
                            f"You can re-fetch from Canvas or enter scores manually."
                        ),
                        buttons=[
                            ConvenorActionButton(
                                label="Review submitter reports",
                                url=workflow_url,
                                outline=True,
                                icon="search",
                            )
                        ],
                    )
                )

            # CTA: all reports ready to complete
            wf_total = workflow.submitter_reports.count()
            wf_rts = (
                db.session.query(func.count())
                .filter(
                    SubmitterReport.workflow_id == workflow.id,
                    SubmitterReport.workflow_state
                    == SubmitterReportWorkflowStates.READY_TO_SIGN_OFF,
                )
                .scalar()
            )
            if wf_total > 0 and wf_rts == wf_total:
                actions.append(
                    ConvenorAction(
                        severity="success",
                        icon="check-circle",
                        title=f"{workflow.name}: all reports ready to complete",
                        description="All submitter reports are in the Ready to sign off state and have grades.",
                        buttons=[
                            ConvenorActionButton(
                                label="Complete all…",
                                icon="check-double",
                                method="POST",
                                url=url_for(
                                    "convenor.complete_all_submitter_reports",
                                    workflow_id=workflow.id,
                                    url=url_for(
                                        "convenor.event_marking_workflows_inspector",
                                        event_id=event_id,
                                    ),
                                    text="Marking workflows",
                                ),
                            )
                        ],
                    )
                )

            # CTA: return all completed reports (admin/root only)
            if is_privileged:
                wf_completed = (
                    db.session.query(func.count())
                    .filter(
                        SubmitterReport.workflow_id == workflow.id,
                        SubmitterReport.workflow_state
                        == SubmitterReportWorkflowStates.COMPLETED,
                    )
                    .scalar()
                )
                if wf_completed > 0:
                    actions.append(
                        ConvenorAction(
                            severity="danger",
                            icon="undo",
                            title=f"{workflow.name}: return completed reports to convenor",
                            description=f"{wf_completed} completed report{'s' if wf_completed != 1 else ''} can be returned for re-editing.",
                            buttons=[
                                ConvenorActionButton(
                                    label="Return all…",
                                    icon="undo",
                                    outline=True,
                                    method="POST",
                                    url=url_for(
                                        "convenor.return_all_submitter_reports",
                                        workflow_id=workflow.id,
                                        url=url_for(
                                            "convenor.event_marking_workflows_inspector",
                                            event_id=event_id,
                                        ),
                                        text="Marking workflows",
                                    ),
                                )
                            ],
                        )
                    )

    # Feedback PDF generation jobs active for this event
    feedback_jobs = (
        db.session.query(FeedbackOrchestrationJob)
        .filter(
            FeedbackOrchestrationJob.event_id == event.id,
            FeedbackOrchestrationJob.status.in_(
                FeedbackOrchestrationJob.ACTIVE_STATUSES
            ),
        )
        .order_by(FeedbackOrchestrationJob.created_at.desc())
        .all()
    )

    _SEVERITY_ORDER = {
        "danger": 0,
        "warning": 1,
        "info": 2,
        "success": 3,
        "secondary": 4,
    }
    actions.sort(key=lambda a: _SEVERITY_ORDER.get(a.severity, 99))

    form = ConfirmActionForm()
    return render_template_context(
        "convenor/markingevent/event_marking_workflows_inspector.html",
        event=event,
        pclass=pclass,
        url=url,
        text=text,
        can_edit=can_edit,
        actions=actions,
        feedback_jobs=feedback_jobs,
        form=form,
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

    can_edit = event.workflow_state != MarkingEventWorkflowStates.CLOSED

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

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
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

    if form.validate_on_submit(
        extra_validators={
            "name": [make_unique_marking_workflow_in_event(event_id)],
            "key": [make_unique_marking_workflow_key_in_event(event_id)],
        }
    ):
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

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
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

    # On GET, pre-populate scheme with the parent MarkingScheme (not the LiveMarkingScheme snapshot),
    # so it matches the choices in the QuerySelectField.
    if request.method == "GET":
        form.scheme.data = workflow.scheme.parent if workflow.scheme else None

    if form.validate_on_submit(
        extra_validators={
            "name": [
                make_unique_marking_workflow_in_event(
                    event.id, name=workflow.name, exclude_id=workflow.id
                )
            ],
            "key": [
                make_unique_marking_workflow_key_in_event(
                    event.id, key=workflow.key, exclude_id=workflow.id
                )
            ],
        }
    ):
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

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot delete workflows from a closed marking event.", "error")
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.event_marking_workflows_inspector", event_id=event.id)
    )
    text = request.args.get("text", "Marking workflows")

    form = ConfirmActionForm()
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
        form=form,
    )


@convenor.route("/confirm_delete_marking_workflow/<int:workflow_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def confirm_delete_marking_workflow(workflow_id):
    """Permanently delete a MarkingWorkflow and all its child records"""
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass
    event_id = event.id

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
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

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
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
    asset: SubmittedAsset = attachment.attachment
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
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
            f'Added attachment "{asset.target_name if asset else attachment.id}" '
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

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
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

    if event.workflow_state not in (
        MarkingEventWorkflowStates.OPEN,
        MarkingEventWorkflowStates.READY_TO_CONFLATE,
        MarkingEventWorkflowStates.READY_TO_GENERATE_FEEDBACK,
        MarkingEventWorkflowStates.READY_TO_PUSH_FEEDBACK,
    ):
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

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot send notifications for a closed marking event.", "error")
        return redirect(redirect_url())

    try:
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.marking.send_marking_emails"]
        task.apply_async(
            kwargs={
                "workflow_id": workflow_id,
                "cc_convenor": True,
                "max_attachment": DEFAULT_MAX_ATTACHMENT_SIZE,
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


@convenor.route("/distribute_for_submitter_report/<int:sr_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def distribute_for_submitter_report(sr_id):
    """Dispatch distribution emails for all distributable MarkingReports of a SubmitterReport."""
    sr: SubmitterReport = SubmitterReport.query.get_or_404(sr_id)
    workflow: MarkingWorkflow = sr.workflow
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.workflow_state not in (
        MarkingEventWorkflowStates.OPEN,
        MarkingEventWorkflowStates.READY_TO_CONFLATE,
        MarkingEventWorkflowStates.READY_TO_GENERATE_FEEDBACK,
        MarkingEventWorkflowStates.READY_TO_PUSH_FEEDBACK,
    ):
        flash(
            "Marking notifications can only be dispatched while the event is open.",
            "error",
        )
        return redirect(redirect_url())

    deadline_str = None
    if workflow.effective_deadline is not None:
        deadline_str = workflow.effective_deadline.isoformat()

    queued = 0
    try:
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.marking.dispatch_single_email"]
        for mr in sr.marking_reports:
            if not mr.distributed:
                task.apply_async(args=[mr.id, True, 10, None, deadline_str, False])
                queued += 1
    except Exception as e:
        current_app.logger.exception(
            "Error dispatching distribute_for_submitter_report", exc_info=e
        )
        flash(
            "Could not dispatch marking notifications. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    if queued > 0:
        flash(
            f"{queued} marking notification{'s' if queued != 1 else ''} for this submitter report {'have' if queued != 1 else 'has'} been queued.",
            "success",
        )
    else:
        flash(
            "No distributable marking reports found for this submitter report.", "info"
        )

    return redirect(redirect_url())


@convenor.route("/send_reminders_for_submitter_report/<int:sr_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def send_reminders_for_submitter_report(sr_id):
    """Dispatch reminder emails for all eligible MarkingReports of a SubmitterReport."""
    sr: SubmitterReport = SubmitterReport.query.get_or_404(sr_id)
    workflow: MarkingWorkflow = sr.workflow
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot send reminders for a closed marking event.", "error")
        return redirect(redirect_url())

    try:
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.marking.send_marking_reminders"]
        task.apply_async(
            kwargs={
                "workflow_id": workflow.id,
                "cc_convenor": True,
                "max_attachment": DEFAULT_MAX_ATTACHMENT_SIZE,
                "test_user_id": None,
                "convenor_id": current_user.id,
                "sr_id": sr.id,
            }
        )
        flash("Reminder emails for this submitter report have been queued.", "success")
    except Exception as e:
        current_app.logger.exception(
            "Error dispatching send_reminders_for_submitter_report", exc_info=e
        )
        flash(
            "Could not dispatch reminder emails. Please contact a system administrator.",
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/send_reminder_for_marking_report/<int:report_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def send_reminder_for_marking_report(report_id):
    """Dispatch a reminder email for a single MarkingReport."""
    report: MarkingReport = MarkingReport.query.get_or_404(report_id)
    sr: SubmitterReport = report.submitter_report
    workflow: MarkingWorkflow = sr.workflow
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot send reminders for a closed marking event.", "error")
        return redirect(redirect_url())

    try:
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.marking.send_marking_reminders"]
        task.apply_async(
            kwargs={
                "workflow_id": workflow.id,
                "cc_convenor": True,
                "max_attachment": DEFAULT_MAX_ATTACHMENT_SIZE,
                "test_user_id": None,
                "convenor_id": current_user.id,
                "mr_id": report.id,
            }
        )
        flash(f"Reminder email for {report.user.name} has been queued.", "success")
    except Exception as e:
        current_app.logger.exception(
            "Error dispatching send_reminder_for_marking_report", exc_info=e
        )
        flash(
            "Could not dispatch reminder email. Please contact a system administrator.",
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

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot send notifications for a closed marking event.", "error")
        return redirect(redirect_url())

    try:
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.marking.send_marking_event_emails"]
        task.apply_async(
            kwargs={
                "event_id": event_id,
                "cc_convenor": True,
                "max_attachment": DEFAULT_MAX_ATTACHMENT_SIZE,
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

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot open a marking event that has already been closed.", "error")
        return redirect(redirect_url())

    if event.workflow_state != MarkingEventWorkflowStates.WAITING:
        flash("This marking event is already open.", "info")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    title = f'Open marking event "{event.name}"'
    panel_title = f"Open marking event <strong>{event.name}</strong>"
    action_url = url_for("convenor.do_open_marking_event", event_id=event_id, url=url)
    test_url = url_for("convenor.test_marking_event", event_id=event_id, url=url)

    # Classify each workflow by what will happen when the event is opened.
    no_email = []    # role has no associated email template; reports marked NOT_REQUIRED automatically
    immediate = []   # email template exists and requires_report=False; emails dispatched immediately
    on_upload = []   # email template exists and requires_report=True; emails deferred until report uploaded
    for wf in event.workflows:
        if wf.resolve_email_template() is None:
            no_email.append(wf)
        elif wf.requires_report:
            on_upload.append(wf)
        else:
            immediate.append(wf)

    message = f"<p>Are you sure you wish to open the marking event <strong>{event.name}</strong>?</p>"

    if not immediate and not on_upload:
        # All workflows require no email notification
        message += (
            "<p>No notification emails will be sent. All marking reports will be marked as "
            "not requiring distribution automatically when the event is opened.</p>"
            "<p>This action cannot be undone.</p>"
        )
        submit_label = "Open event"
    else:
        # At least some workflows will send emails
        if on_upload:
            n = len(on_upload)
            wf_label = f"{n} workflow{'s' if n != 1 else ''}"
            message += (
                f"<p>Marking notification emails will be dispatched for {wf_label} once student "
                f"reports have been uploaded. Catch-up notifications can be sent later for any "
                f"reports uploaded subsequently.</p>"
            )
        if immediate:
            n = len(immediate)
            wf_label = f"{n} workflow{'s' if n != 1 else ''}"
            message += (
                f"<p>Marking notification emails for {wf_label} will be dispatched immediately, "
                f"as no submitted report is required before marking can begin.</p>"
            )
        if no_email:
            n = len(no_email)
            message += (
                f"<p>{n} workflow{'s' if n != 1 else ''} require no email notification and will "
                f"be marked as distributed automatically.</p>"
            )
        message += (
            f'<p>To send a test distribution first, <a href="{test_url}">click here to run a test</a>.</p>'
            f"<p>This action cannot be undone.</p>"
        )
        submit_label = "Open event and send notifications"

    form = ConfirmActionForm()
    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
        form=form,
    )


@convenor.route("/do_open_marking_event/<int:event_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def do_open_marking_event(event_id):
    """Set event.workflow_state = OPEN and dispatch marking emails for all workflows."""
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot open a marking event that has already been closed.", "error")
        return redirect(redirect_url())

    if event.workflow_state != MarkingEventWorkflowStates.WAITING:
        flash("This marking event is already open.", "info")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    event.workflow_state = MarkingEventWorkflowStates.OPEN
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
                "max_attachment": DEFAULT_MAX_ATTACHMENT_SIZE,
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

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
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
                    "max_attachment": DEFAULT_MAX_ATTACHMENT_SIZE,
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


@convenor.route("/send_reminder_for_workflow/<int:workflow_id>")
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def send_reminder_for_workflow(workflow_id):
    """Show a confirmation page before dispatching marking reminder emails for a workflow."""
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot send reminders for a closed marking event.", "error")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    text = request.args.get("text", "Marking workflows")

    # Count eligible reminder targets (same logic as has_reminder_eligible_reports,
    # but counting individual targets including per-responsible-supervisor items)
    _blocking = {
        SubmitterReportWorkflowStates.NOT_READY,
        SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION,
        SubmitterReportWorkflowStates.NEEDS_MODERATOR_ASSIGNED,
    }
    _supervisor_roles = {
        SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
        SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
    }
    eligible_count = 0
    for sr in workflow.submitter_reports:
        if sr.workflow_state in _blocking:
            continue
        for mr in sr.marking_reports:
            if not mr.distributed:
                continue
            if not mr.report_submitted:
                eligible_count += 1
            elif mr.role.role in _supervisor_roles and (
                sr.workflow_state
                == SubmitterReportWorkflowStates.AWAITING_RESPONSIBLE_SUPERVISOR_SIGNOFF
            ):
                eligible_count += mr.responsible_supervisors.count()

    test_url = url_for(
        "convenor.test_send_reminder_for_workflow",
        workflow_id=workflow_id,
        url=url,
        text=text,
    )
    action_url = url_for(
        "convenor.do_send_reminder_for_workflow", workflow_id=workflow_id, url=url
    )

    title = f'Send reminders for workflow "{workflow.name}"'
    panel_title = (
        f"Send marking reminders for workflow <strong>{workflow.name}</strong>"
    )
    message = (
        f"<p>Are you sure you wish to send reminder emails for the workflow "
        f"<strong>{workflow.name}</strong>?</p>"
        f"<p>{eligible_count} reminder email{'s' if eligible_count != 1 else ''} will be dispatched "
        f"to assessors who have not yet submitted their marking report, or to responsible supervisors "
        f"who have not yet signed off a submitted report.</p>"
        f"<p>To send a test reminder first, "
        f'<a href="{test_url}">click here to run a test</a>.</p>'
    )
    submit_label = "Send reminders"

    form = ConfirmActionForm()
    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
        form=form,
    )


@convenor.route("/do_send_reminder_for_workflow/<int:workflow_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root", "office", "convenor")
def do_send_reminder_for_workflow(workflow_id):
    """Dispatch marking reminder emails for all eligible MarkingReports in a workflow."""
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot send reminders for a closed marking event.", "error")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    try:
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.marking.send_marking_reminders"]
        task.apply_async(
            kwargs={
                "workflow_id": workflow_id,
                "cc_convenor": True,
                "max_attachment": DEFAULT_MAX_ATTACHMENT_SIZE,
                "test_user_id": None,
                "convenor_id": current_user.id,
            }
        )
        flash(
            f'Marking reminders for workflow "{workflow.name}" have been queued.',
            "success",
        )
    except Exception as e:
        current_app.logger.exception(
            "Error dispatching send_marking_reminders", exc_info=e
        )
        flash(
            "Could not dispatch marking reminders. Please contact a system administrator.",
            "error",
        )

    return redirect(url)


@convenor.route(
    "/test_send_reminder_for_workflow/<int:workflow_id>", methods=["GET", "POST"]
)
@roles_accepted("faculty", "admin", "root")
def test_send_reminder_for_workflow(workflow_id):
    """Show a form to select a test recipient, then dispatch a test reminder for a workflow."""
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot send test reminders for a closed marking event.", "error")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    text = request.args.get("text", "Marking workflows")

    TestMarkingReminderForm = TestMarkingReminderFormFactory(pclass)
    form = TestMarkingReminderForm(request.form)

    if form.validate_on_submit():
        test_user_id = form.test_target.data.id
        try:
            celery = current_app.extensions["celery"]
            task = celery.tasks["app.tasks.marking.send_marking_reminders"]
            task.apply_async(
                kwargs={
                    "workflow_id": workflow_id,
                    "cc_convenor": True,
                    "max_attachment": DEFAULT_MAX_ATTACHMENT_SIZE,
                    "test_user_id": test_user_id,
                    "convenor_id": current_user.id,
                }
            )
            flash(
                f'Test reminders for workflow "{workflow.name}" have been queued '
                f"to {form.test_target.data.name}.",
                "success",
            )
        except Exception as e:
            current_app.logger.exception(
                "Error dispatching test send_marking_reminders", exc_info=e
            )
            flash(
                "Could not dispatch test reminders. Please contact a system administrator.",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "convenor/markingevent/test_send_reminder_for_workflow.html",
        workflow=workflow,
        event=event,
        form=form,
        url=url,
        title=f'Test reminders for "{workflow.name}"',
        formtitle=f"Send test reminders for workflow <strong>{workflow.name}</strong>",
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

    url = request.args.get(
        "url", url_for("convenor.marking_reports_inspector", workflow_id=workflow.id)
    )

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot modify reports in a closed marking event.", "error")
        return redirect(url)

    report.report_submitted = False
    report.grade = None

    report.grade_submitted_by_id = None
    report.grade_submitted_timestamp = None

    # Clearing the grade invalidates any existing sign-off — the responsible supervisor
    # approved a grade that is now being revoked, so the report must go through the
    # sign-off cycle again once the assessor resubmits.
    report.signed_off_id = None
    report.signed_off_timestamp = None
    for role in report.responsible_supervisors.all():
        report.responsible_supervisors.remove(role)

    # Cancel the existing close_marking_window scheduler entry for this report so that
    # a fresh 24 h window is created when the assessor resubmits their grade.
    # schedule_close_marking_window has an idempotency guard that skips creation if an
    # entry already exists, so we must remove the stale one here.
    from ..sqlalchemy_scheduler import CrontabSchedule, DatabaseSchedulerEntry

    existing_entry = (
        db.session.query(DatabaseSchedulerEntry)
        .filter(
            DatabaseSchedulerEntry.name.like(f"close_marking_window_mr{report.id}_%")
        )
        .first()
    )
    if existing_entry is not None:
        crontab_id = existing_entry.crontab_id
        db.session.delete(existing_entry)
        if crontab_id is not None:
            crontab = db.session.query(CrontabSchedule).filter_by(id=crontab_id).first()
            if crontab is not None:
                db.session.delete(crontab)

    try:
        log_db_commit(
            f"Cleared marking grade and sign-off for report #{report.id} (workflow: {workflow.name})",
            user=current_user,
            project_classes=pclass,
        )
        flash(
            f"The marking form for {report.user.name} has been re-opened and any sign-off has been cleared. "
            "The assessor can now resubmit their report.",
            "success",
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not clear marking grade due to a database error.", "error")

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

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot modify reports in a closed marking event.", "error")
        return redirect(url)

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
    from ..tasks.markingevent import _assign_moderator

    sr = (
        db.session.query(SubmitterReport)
        .filter_by(id=submitter_report_id)
        .first_or_404()
    )
    workflow = sr.workflow
    event = workflow.event
    pclass = event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.submitter_reports_inspector", workflow_id=workflow.id)
    )

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot modify reports in a closed marking event.", "error")
        return redirect(url)

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
    pclass = workflow.event.pclass

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    sr.grade = mod_report.grade
    sr.grade_generated_by_id = current_user.id
    sr.grade_generated_timestamp = datetime.now()
    sr.workflow_state = SubmitterReportWorkflowStates.READY_TO_SIGN_OFF
    sr.accepted_moderator_report_id = mod_report.id
    sr.moderator_accepted_id = mod_report.role_id
    sr.moderator_accepted_timestamp = datetime.now()

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


@convenor.route("/complete-submitter-report/<int:sr_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def complete_submitter_report(sr_id):
    """Move a single SubmitterReport from READY_TO_SIGN_OFF to COMPLETED."""
    sr: SubmitterReport = SubmitterReport.query.get_or_404(sr_id)
    workflow: MarkingWorkflow = sr.workflow
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.period.config.project_class

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = url_for("convenor.submitter_reports_inspector", workflow_id=workflow.id)

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot modify reports in a closed marking event.", "error")
        return redirect(url)

    if sr.workflow_state != SubmitterReportWorkflowStates.READY_TO_SIGN_OFF:
        flash("This report is not in the Ready to sign off state.", "error")
        return redirect(url)

    if sr.grade is None:
        flash("Cannot sign off a report that does not have a grade assigned.", "error")
        return redirect(url)

    now = datetime.now()
    sr.signed_off_id = current_user.id
    sr.signed_off_timestamp = now
    sr.completed_by_id = current_user.id
    sr.completed_timestamp = now
    sr.workflow_state = SubmitterReportWorkflowStates.COMPLETED

    workflow.refresh_completed()
    event.refresh_completed()

    try:
        log_db_commit(
            f"Completed SubmitterReport #{sr.id} for student {sr.student.user.name} "
            f"in workflow '{workflow.name}' (event: {event.name})",
            user=current_user,
            project_classes=pclass,
        )
        flash("Report signed off.", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not sign off report due to a database error.", "error")

    return redirect(url)


@convenor.route(
    "/complete-all-submitter-reports/<int:workflow_id>", methods=["GET", "POST"]
)
@roles_accepted("faculty", "admin", "root")
def complete_all_submitter_reports(workflow_id):
    """
    GET: Show a confirmation page listing the reports that will be completed.
    POST: Move all READY_TO_SIGN_OFF SubmitterReports in a workflow to COMPLETED.
    """
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.period.config.project_class

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.event_marking_workflows_inspector", event_id=event.id)
    )
    text = request.args.get("text", "Marking workflows")

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot modify reports in a closed marking event.", "error")
        return redirect(url)

    # Count reports eligible for completion
    ready_reports = [
        sr
        for sr in workflow.submitter_reports.all()
        if sr.workflow_state == SubmitterReportWorkflowStates.READY_TO_SIGN_OFF
        and sr.grade is not None
    ]
    no_grade_reports = [
        sr
        for sr in workflow.submitter_reports.all()
        if sr.workflow_state == SubmitterReportWorkflowStates.READY_TO_SIGN_OFF
        and sr.grade is None
    ]

    form = ActionForm(request.form)

    if request.method == "GET":
        return render_template_context(
            "convenor/markingevent/confirm_complete_all.html",
            workflow=workflow,
            event=event,
            pclass=pclass,
            url=url,
            text=text,
            ready_reports=ready_reports,
            no_grade_reports=no_grade_reports,
            form=form,
        )

    # POST path
    if not form.validate_on_submit():
        flash("Invalid request.", "error")
        return redirect(url)

    now = datetime.now()
    completed_count = 0
    skipped_count = 0

    try:
        for sr in workflow.submitter_reports.all():
            if sr.workflow_state != SubmitterReportWorkflowStates.READY_TO_SIGN_OFF:
                continue
            if sr.grade is None:
                skipped_count += 1
                continue
            sr.signed_off_id = current_user.id
            sr.signed_off_timestamp = now
            sr.completed_by_id = current_user.id
            sr.completed_timestamp = now
            sr.workflow_state = SubmitterReportWorkflowStates.COMPLETED
            completed_count += 1

        workflow.refresh_completed()
        event.refresh_completed()

        if completed_count > 0:
            msg = f"Completed {completed_count} SubmitterReport(s) in workflow '{workflow.name}' (event: {event.name})"
            if skipped_count > 0:
                msg += f"; skipped {skipped_count} without a grade"
            log_db_commit(msg, user=current_user, project_classes=pclass)
            flash(
                f"{completed_count} report(s) signed off."
                + (f" {skipped_count} skipped (no grade)." if skipped_count else ""),
                "success",
            )
        else:
            db.session.commit()
            flash("No reports were in the Ready to sign off state.", "info")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not sign off reports due to a database error.", "error")

    return redirect(url)


@convenor.route("/drop-submitter-report/<int:sr_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def drop_submitter_report(sr_id):
    """
    GET: Confirmation page before withdrawing a SubmitterReport from the marking event.
    POST: Perform the withdrawal, setting workflow_state to DROPPED.
    """
    sr: SubmitterReport = SubmitterReport.query.get_or_404(sr_id)
    workflow: MarkingWorkflow = sr.workflow
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.period.config.project_class

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = url_for("convenor.submitter_reports_inspector", workflow_id=workflow.id)

    _terminal = {
        SubmitterReportWorkflowStates.DROPPED,
        SubmitterReportWorkflowStates.COMPLETED,
        SubmitterReportWorkflowStates.FEEDBACK_AVAILABLE,
    }

    if request.method == "GET":
        student_name = (
            sr.student.user.name if sr.student else f"SubmitterReport #{sr_id}"
        )
        form = ActionForm()
        return render_template_context(
            "admin/danger_confirm.html",
            title="Withdraw student from marking event",
            panel_title="Withdraw student from marking event",
            message=(
                f"<p>You are about to withdraw <strong>{student_name}</strong> from the "
                f"marking workflow <strong>{workflow.name}</strong>.</p>"
                f"<p>Once withdrawn, this student will be excluded from all marking "
                f"activity: no emails will be sent to their assigned assessors, the "
                f"marking forms will be inaccessible, and no feedback will be generated "
                f"for this student.</p>"
                f"<p><strong>This action can only be reversed by an administrator.</strong> "
                f"The student's role assignments will remain visible to their assigned "
                f"staff with a notice that no marking report is required.</p>"
            ),
            action_url=url_for("convenor.drop_submitter_report", sr_id=sr_id),
            submit_label="Withdraw student",
            form=form,
            url=url,
            text="Submitter reports",
        )

    form = ActionForm(request.form)
    if not form.validate_on_submit():
        flash("Invalid request.", "error")
        return redirect(url)

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot modify reports in a closed marking event.", "error")
        return redirect(url)

    if sr.workflow_state in _terminal:
        flash(
            "This report is already in a terminal state and cannot be withdrawn.",
            "error",
        )
        return redirect(url)

    sr.workflow_state = SubmitterReportWorkflowStates.DROPPED
    workflow.refresh_completed()
    event.refresh_completed()

    try:
        student_name = sr.student.user.name if sr.student else f"#{sr_id}"
        log_db_commit(
            f"Withdrew SubmitterReport #{sr.id} for student {student_name} from "
            f"workflow '{workflow.name}' (event: {event.name})",
            user=current_user,
            project_classes=pclass,
        )
        flash(f"Student withdrawn from marking workflow '{workflow.name}'.", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not withdraw student due to a database error.", "error")

    return redirect(url)


@convenor.route("/return-submitter-report/<int:sr_id>", methods=["POST"])
@roles_accepted("admin", "root")
def return_submitter_report_to_convenor(sr_id):
    """Return a single COMPLETED or DROPPED SubmitterReport to convenor control (admin/root only)."""
    sr: SubmitterReport = SubmitterReport.query.get_or_404(sr_id)
    workflow: MarkingWorkflow = sr.workflow
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.period.config.project_class

    url = url_for("convenor.submitter_reports_inspector", workflow_id=workflow.id)

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot modify reports in a closed marking event.", "error")
        return redirect(url)

    _returnable = {
        SubmitterReportWorkflowStates.COMPLETED,
        SubmitterReportWorkflowStates.DROPPED,
    }
    if sr.workflow_state not in _returnable:
        flash(
            "This report cannot be returned — it is not in the Completed or Withdrawn state.",
            "error",
        )
        return redirect(url)

    from_dropped = sr.workflow_state == SubmitterReportWorkflowStates.DROPPED

    if from_dropped:
        sr.workflow_state = SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE
    else:
        sr.workflow_state = SubmitterReportWorkflowStates.READY_TO_SIGN_OFF
        sr.completed_by_id = None
        sr.completed_timestamp = None

    workflow.refresh_completed()
    event.refresh_completed()

    if not from_dropped:
        # Mark any existing ConflationReports for this event as stale.
        # No ConflationReports exist for DROPPED records, so this is only needed for COMPLETED.
        for cr in event.conflation_reports.all():
            cr.is_stale = True

    try:
        from_label = "Withdrawn" if from_dropped else "Completed"
        log_db_commit(
            f"Returned SubmitterReport #{sr.id} for student {sr.student.user.name} "
            f"to convenor from {from_label} state in workflow '{workflow.name}' (event: {event.name})",
            user=current_user,
            project_classes=pclass,
        )
        flash("Report returned to convenor for editing.", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not return report due to a database error.", "error")

    return redirect(url)


@convenor.route(
    "/return-all-submitter-reports/<int:workflow_id>", methods=["GET", "POST"]
)
@roles_accepted("admin", "root")
def return_all_submitter_reports(workflow_id):
    """
    GET: Show a confirmation page listing the reports that will be returned.
    POST: Return all COMPLETED or DROPPED SubmitterReports in a workflow to convenor control (admin/root only).
    """
    workflow: MarkingWorkflow = MarkingWorkflow.query.get_or_404(workflow_id)
    event: MarkingEvent = workflow.event
    pclass: ProjectClass = event.period.config.project_class

    if not validate_is_convenor(pclass, allow_roles=["admin", "root"]):
        return redirect(redirect_url())

    url = request.args.get(
        "url", url_for("convenor.event_marking_workflows_inspector", event_id=event.id)
    )
    text = request.args.get("text", "Marking workflows")

    if event.workflow_state == MarkingEventWorkflowStates.CLOSED:
        flash("Cannot modify reports in a closed marking event.", "error")
        return redirect(url)

    _returnable = {
        SubmitterReportWorkflowStates.COMPLETED,
        SubmitterReportWorkflowStates.DROPPED,
    }
    returnable_reports = [
        sr
        for sr in workflow.submitter_reports.all()
        if sr.workflow_state in _returnable
    ]

    form = ActionForm(request.form)

    if request.method == "GET":
        return render_template_context(
            "convenor/markingevent/confirm_return_all.html",
            workflow=workflow,
            event=event,
            pclass=pclass,
            url=url,
            text=text,
            completed_reports=returnable_reports,
            form=form,
        )

    # POST path
    if not form.validate_on_submit():
        flash("Invalid request.", "error")
        return redirect(url)

    returned_count = 0
    any_completed = False

    try:
        for sr in workflow.submitter_reports.all():
            if sr.workflow_state == SubmitterReportWorkflowStates.COMPLETED:
                sr.workflow_state = SubmitterReportWorkflowStates.READY_TO_SIGN_OFF
                sr.completed_by_id = None
                sr.completed_timestamp = None
                returned_count += 1
                any_completed = True
            elif sr.workflow_state == SubmitterReportWorkflowStates.DROPPED:
                sr.workflow_state = SubmitterReportWorkflowStates.READY_TO_DISTRIBUTE
                returned_count += 1

        workflow.refresh_completed()
        event.refresh_completed()

        if any_completed:
            # Mark any existing ConflationReports for this event as stale.
            # Not needed for DROPPED returns since no ConflationReport exists for those records.
            for cr in event.conflation_reports.all():
                cr.is_stale = True

        if returned_count > 0:
            log_db_commit(
                f"Returned {returned_count} SubmitterReport(s) in workflow '{workflow.name}' "
                f"to convenor from Completed/Withdrawn state (event: {event.name})",
                user=current_user,
                project_classes=pclass,
            )
            flash(
                f"{returned_count} report(s) returned to convenor for editing.",
                "success",
            )
        else:
            db.session.commit()
            flash("No signed-off or withdrawn reports found in this workflow.", "info")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not return reports due to a database error.", "error")

    return redirect(url)


# ---------------------------------------------------------------------------
# CONFLATION
# ---------------------------------------------------------------------------


@convenor.route("/calculate-conflation/<int:event_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def calculate_conflation(event_id):
    """
    Calculate conflated target marks for all SubmissionRecords in a MarkingEvent.

    GET: render a confirmation page showing the number of records to be processed.
    POST: perform the calculation, advance the event state, and redirect.

    Requires that the event is in the completed state (all MarkingWorkflows completed).
    Discards any existing ConflationReport instances for this event and generates a fresh set.
    """
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.period.config.project_class

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = url_for("convenor.event_marking_workflows_inspector", event_id=event_id)

    if event.workflow_state < MarkingEventWorkflowStates.READY_TO_CONFLATE:
        flash(
            "Cannot calculate conflation: not all marking workflows are complete.",
            "error",
        )
        return redirect(url)

    if request.method == "GET":
        submission_count = event.period.submissions.count()
        existing_reports = event.conflation_reports.count()
        any_stale = (
            existing_reports > 0
            and event.conflation_reports.filter_by(is_stale=True).count() > 0
        )
        form = ActionForm()
        return render_template_context(
            "convenor/markingevent/confirm_calculate_conflation.html",
            event=event,
            pclass=pclass,
            submission_count=submission_count,
            existing_reports=existing_reports,
            any_stale=any_stale,
            form=form,
            url=url,
            text="Marking workflows",
        )

    form = ActionForm(request.form)
    if not form.validate_on_submit():
        flash("Invalid request.", "error")
        return redirect(url)

    targets = event.targets_as_dict
    if not targets:
        flash("This event has no conflation targets defined.", "error")
        return redirect(url)

    workflows = event.workflows.all()

    try:
        # Discard all existing ConflationReports for this event
        event.conflation_reports.delete()

        submissions = event.period.submissions.all()
        now = datetime.now()
        generated_count = 0
        dropped_count = 0

        for record in submissions:
            # Build grades dict: {workflow.key: float(sr.grade)}
            # Skip records where any workflow has a DROPPED SubmitterReport.
            grades = {}
            skip_record = False
            for wf in workflows:
                sr = (
                    db.session.query(SubmitterReport)
                    .filter_by(record_id=record.id, workflow_id=wf.id)
                    .first()
                )
                if sr is None:
                    flash(
                        f"Conflation failed: no SubmitterReport found for student "
                        f"'{record.owner.student.user.name}' in workflow '{wf.name}'. "
                        f"All ConflationReports have been discarded.",
                        "error",
                    )
                    db.session.rollback()
                    return redirect(url)
                if sr.workflow_state == SubmitterReportWorkflowStates.DROPPED:
                    skip_record = True
                    break
                if sr.grade is None:
                    flash(
                        f"Conflation failed: SubmitterReport for student "
                        f"'{record.owner.student.user.name}' in workflow '{wf.name}' "
                        f"has no grade. All ConflationReports have been discarded.",
                        "error",
                    )
                    db.session.rollback()
                    return redirect(url)
                grades[wf.key] = float(sr.grade)

            if skip_record:
                dropped_count += 1
                continue

            # Evaluate each target expression in the restricted namespace, then apply
            # the institutional rounding policy to produce whole-number module marks.
            result = {}
            for target_name, expr in targets.items():
                try:
                    value = eval(expr, {"__builtins__": {}}, grades)  # noqa: S307
                    result[target_name] = ACTIVE_ROUNDING_POLICY.round(float(value))
                except Exception as exc:
                    flash(
                        f"Conflation failed: error evaluating target '{target_name}' "
                        f"(expression: {expr!r}) for student "
                        f"'{record.owner.student.user.name}': {exc}. "
                        f"All ConflationReports have been discarded.",
                        "error",
                    )
                    db.session.rollback()
                    return redirect(url)

            cr = ConflationReport(
                marking_event_id=event.id,
                submission_record_id=record.id,
                conflation_report=json.dumps(
                    {
                        "targets": result,
                        "metadata": {
                            "rounding_policy": ACTIVE_ROUNDING_POLICY.identifier
                        },
                    }
                ),
                generated_by_id=current_user.id,
                generated_timestamp=now,
                is_stale=False,
            )
            db.session.add(cr)
            generated_count += 1

        event.workflow_state = MarkingEventWorkflowStates.READY_TO_GENERATE_FEEDBACK
        log_db_commit(
            f"Calculated conflation for {generated_count} SubmissionRecord(s) in event "
            f"'{event.name}' ({pclass.name})",
            user=current_user,
            project_classes=pclass,
        )
        flash(f"Conflation complete: {generated_count} record(s) processed.", "success")
        if dropped_count > 0:
            flash(
                f"{dropped_count} withdrawn student(s) were excluded from conflation.",
                "info",
            )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception(
            "SQLAlchemyError in calculate_conflation", exc_info=e
        )
        flash("Could not calculate conflation due to a database error.", "error")

    return redirect(url)


# ---------------------------------------------------------------------------
# GRADE BACK-PROPAGATION
# ---------------------------------------------------------------------------


def _propagate_grade_to_records(
    event: MarkingEvent,
    target_key: str,
    grade_field: str,
    generated_id_field: str,
    generated_ts_field: str,
    event_id_field: str,
    pclass: ProjectClass,
) -> tuple[int, str | None]:
    """
    Copy the named target value from each ConflationReport to the given SubmissionRecord field.
    Also records which MarkingEvent was the source of the grade in event_id_field.

    Returns (count_updated, error_message).  error_message is None on success.
    """
    conflation_reports = event.conflation_reports.all()
    if not conflation_reports:
        return 0, "No conflation results exist for this event."

    now = datetime.now()
    updated = 0
    for cr in conflation_reports:
        result = cr.conflation_report_as_dict
        if target_key not in result:
            continue
        record = cr.submission_record
        setattr(record, grade_field, result[target_key])
        setattr(record, generated_id_field, current_user.id)
        setattr(record, generated_ts_field, now)
        setattr(record, event_id_field, event.id)
        updated += 1

    return updated, None


@convenor.route("/propagate-report-grade/<int:event_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def propagate_report_grade(event_id):
    """Copy the 'report' conflation target to SubmissionRecord.report_grade."""
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.period.config.project_class

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = url_for("convenor.marking_event_conflation_reports", event_id=event_id)

    form = ActionForm(request.form)
    if not form.validate_on_submit():
        flash("Invalid request.", "error")
        return redirect(url)

    try:
        count, err = _propagate_grade_to_records(
            event,
            "report",
            "report_grade",
            "report_generated_id",
            "report_generated_timestamp",
            "report_event_id",
            pclass,
        )
        if err:
            flash(err, "error")
            return redirect(url)
        log_db_commit(
            f"Propagated 'report' grades from conflation to {count} SubmissionRecord(s) "
            f"in event '{event.name}' ({pclass.name})",
            user=current_user,
            project_classes=pclass,
        )
        flash(f"Report grades copied to {count} submission record(s).", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception(
            "SQLAlchemyError in propagate_report_grade", exc_info=e
        )
        flash("Could not propagate report grades due to a database error.", "error")

    return redirect(url)


@convenor.route("/propagate-supervision-grade/<int:event_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def propagate_supervision_grade(event_id):
    """Copy the 'supervisor' conflation target to SubmissionRecord.supervision_grade."""
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.period.config.project_class

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = url_for("convenor.marking_event_conflation_reports", event_id=event_id)

    form = ActionForm(request.form)
    if not form.validate_on_submit():
        flash("Invalid request.", "error")
        return redirect(url)

    try:
        count, err = _propagate_grade_to_records(
            event,
            "supervisor",
            "supervision_grade",
            "supervision_generated_id",
            "supervision_generated_timestamp",
            "supervision_event_id",
            pclass,
        )
        if err:
            flash(err, "error")
            return redirect(url)
        log_db_commit(
            f"Propagated 'supervisor' grades from conflation to {count} SubmissionRecord(s) "
            f"in event '{event.name}' ({pclass.name})",
            user=current_user,
            project_classes=pclass,
        )
        flash(f"Supervision grades copied to {count} submission record(s).", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception(
            "SQLAlchemyError in propagate_supervision_grade", exc_info=e
        )
        flash(
            "Could not propagate supervision grades due to a database error.", "error"
        )

    return redirect(url)


@convenor.route("/propagate-presentation-grade/<int:event_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def propagate_presentation_grade(event_id):
    """Copy the 'presentation' conflation target to SubmissionRecord.presentation_grade."""
    event: MarkingEvent = MarkingEvent.query.get_or_404(event_id)
    pclass: ProjectClass = event.period.config.project_class

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = url_for("convenor.marking_event_conflation_reports", event_id=event_id)

    form = ActionForm(request.form)
    if not form.validate_on_submit():
        flash("Invalid request.", "error")
        return redirect(url)

    try:
        count, err = _propagate_grade_to_records(
            event,
            "presentation",
            "presentation_grade",
            "presentation_generated_id",
            "presentation_generated_timestamp",
            "presentation_event_id",
            pclass,
        )
        if err:
            flash(err, "error")
            return redirect(url)
        log_db_commit(
            f"Propagated 'presentation' grades from conflation to {count} SubmissionRecord(s) "
            f"in event '{event.name}' ({pclass.name})",
            user=current_user,
            project_classes=pclass,
        )
        flash(f"Presentation grades copied to {count} submission record(s).", "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception(
            "SQLAlchemyError in propagate_presentation_grade", exc_info=e
        )
        flash(
            "Could not propagate presentation grades due to a database error.", "error"
        )

    return redirect(url)


@convenor.route("/marking_report_distribution_status/<int:mr_id>")
@login_required
def marking_report_distribution_status(mr_id):
    mr = db.session.query(MarkingReport).filter_by(id=mr_id).first_or_404()
    return jsonify({"state": mr.distribution_state})
