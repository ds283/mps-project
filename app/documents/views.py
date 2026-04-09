#
# Created by David Seery on 05/01/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime, timedelta
from functools import partial

import requests as http_requests
from bokeh.embed import components
from bokeh.layouts import column
from bokeh.models import Label, Span
from bokeh.plotting import figure
from celery import chain, chord
from flask import (
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    request,
    session,
    stream_with_context,
    url_for,
)
from flask_security import current_user, login_required, roles_accepted
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError

import app.ajax as ajax
import app.shared.cloud_object_store.bucket_types as buckets
from app.shared.llm_thresholds import (
    BURSTINESS_NOTE_HIGH,
    BURSTINESS_NOTE_LOW,
    BURSTINESS_STRONG_HIGH,
    BURSTINESS_STRONG_LOW,
    MATTR_NOTE_HIGH_THRESHOLD,
    MATTR_NOTE_LOW_THRESHOLD,
    MATTR_STRONG_THRESHOLD,
    MTLD_HIGH_NOTE_THRESHOLD,
    MTLD_NOTE_THRESHOLD,
    MTLD_STRONG_THRESHOLD,
    SENT_CV_NOTE_HIGH,
    SENT_CV_NOTE_LOW,
    SENT_CV_STRONG_HIGH,
    SENT_CV_STRONG_LOW,
)

from ..database import db
from ..models import (
    AssetLicense,
    FeedbackReport,
    GeneratedAsset,
    PeriodAttachment,
    ProjectClass,
    ProjectClassConfig,
    Role,
    SubmissionAttachment,
    SubmissionPeriodRecord,
    SubmissionRecord,
    SubmittedAsset,
    SubmittingStudent,
    ThumbnailAsset,
    User,
)
from ..models.submissions import SubmissionRoleTypesMixin
from ..shared.asset_tools import AssetUploadManager
from ..shared.context.global_context import render_template_context
from ..shared.forms.forms import SelectSubmissionRecordFormFactory
from ..shared.utils import redirect_url
from ..shared.validators import validate_is_convenor
from ..shared.workflow_logging import log_db_commit
from ..tasks.thumbnails import dispatch_thumbnail_task
from . import documents
from .forms import (
    EditReportForm,
    EditSubmissionRecordSettingsForm,
    EditSubmitterAttachmentFormFactory,
    UploadReportForm,
    UploadSubmitterAttachmentFormFactory,
)
from .utils import is_admin, is_deletable, is_editable, is_listable, is_uploadable

ATTACHMENT_TYPE_PERIOD = 0
ATTACHMENT_TYPE_SUBMISSION = 1
ATTACHMENT_TYPE_UPLOADED_REPORT = 2
ATTACHMENT_TYPE_PROCESSED_REPORT = 3
ATTACHMENT_TYPE_FEEDBACK_REPORT = 4


@documents.route("/submitter_documents", methods=["GET", "POST"])
@login_required
def submitter_documents():
    sub_id = request.args.get("sub_id", None)
    sid = request.args.get("sid", None)

    # reject request if neither sub_id nor sid is specified
    if sub_id is None and sid is None:
        abort(404)

    submitter: SubmittingStudent = (
        SubmittingStudent.query.get_or_404(sub_id) if sub_id is not None else None
    )
    record: SubmissionRecord = (
        SubmissionRecord.query.get_or_404(sid) if sid is not None else None
    )

    if submitter is not None:
        config: ProjectClassConfig = submitter.config
    else:
        config: ProjectClassConfig = record.period.config

    # construct selector form
    is_admin = validate_is_convenor(config.project_class, message=False)
    SelectSubmissionRecordForm = SelectSubmissionRecordFormFactory(config, is_admin)
    form: SelectSubmissionRecordForm = SelectSubmissionRecordForm(request.form)

    # if submitter and record are both specified, check that SubmissionRecord belongs to it.
    # otherwise, we select the SubmissionRecord corresponding to the current period
    if submitter is not None:
        if record is not None:
            if record.owner.id != submitter.id:
                flash(
                    "Cannot show submitter documents for this combination of student and submission record, "
                    "because the specified submission record does not belong to the student",
                    "info",
                )
                return redirect(redirect_url())

        else:
            if hasattr(form, "selector") and form.selector.data is not None:
                record: SubmissionRecord = submitter.get_assignment(
                    period=form.selector.data
                )
            else:
                record: SubmissionRecord = submitter.get_assignment()

    else:
        # submitter was not specified, so SubmissionRecord must have been.
        # we extract the SubmittingStudent from the record
        assert record is not None
        submitter = record.owner

    # determine if the currently-logged-in user has permissions to view the documents associated with this
    # submission record
    if not is_listable(record, message=True):
        return redirect(redirect_url())

    # ensure form selector reflects the record that is actually being displayed
    period: SubmissionPeriodRecord = record.period
    if hasattr(form, "selector"):
        form.selector.data = period

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    return render_template_context(
        "documents/submitter_manager.html",
        submitter=submitter,
        record=record,
        period=period,
        url=url,
        text=text,
        form=form,
        is_editable=partial(
            is_editable, record, period=period, config=config, message=False
        ),
        deletable=is_deletable(record, period=period, config=config, message=False),
        report_uploadable=is_uploadable(
            record, message=False, allow_student=False, allow_faculty=False
        ),
        attachment_uploadable=is_uploadable(
            record, message=False, allow_student=True, allow_faculty=True
        ),
    )


@documents.route("/generate_processed_report/<int:sid>")
def generate_processed_report(sid):
    # sid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    # nothing to do if no report attached
    if record.report is None:
        flash(
            "Could not initiate processing of the report for this submitter because no report has been attached.",
            "info",
        )
        return redirect(redirect_url())

    # validate user has permission to carry out deletions
    if not is_deletable(record, message=True):
        return redirect(redirect_url())

    if record.processed_report:
        flash(
            "Could not initiate processing of the report for this submitter because a processed report is already attached",
            "info",
        )
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]

    process = celery.tasks["app.tasks.process_report.process"]
    finalize = celery.tasks["app.tasks.process_report.finalize"]
    error = celery.tasks["app.tasks.process_report.error"]

    work = chain(process.si(record.id), finalize.si(record.id)).on_error(
        error.si(record.id, current_user.id)
    )
    work.apply_async()

    record.celery_started = True
    record.celery_finished = None

    try:
        log_db_commit(
            "Initiated report processing for submission record",
            project_classes=record.owner.config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            "A database error was encountered while initiating processing. Please contact an administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@documents.route("/clear_and_regenerate_processed_report/<int:sid>")
@login_required
def clear_and_regenerate_processed_report(sid):
    """
    Clear the existing processed report (DB record + physical object-store asset) and
    re-trigger the process_report Celery chain.  LLM analysis results are left untouched.

    Requires the LLM analysis to have completed successfully, since the cover page
    embeds LLM outputs.
    """
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    if not (current_user.has_role("root") or current_user.has_role("admin")):
        abort(403)

    if not record.language_analysis_complete:
        flash(
            "Cannot regenerate the processed report because language analysis has not completed successfully.",
            "info",
        )
        return redirect(redirect_url())

    if not is_deletable(record, message=True):
        return redirect(redirect_url())

    # Delete existing processed report from DB and object store
    if record.processed_report is not None:
        old_asset = record.processed_report
        record.processed_report_id = None
        try:
            object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
            from ..shared.cloud_object_store.base import ObjectStore

            store: ObjectStore = object_store
            if store is not None:
                store.delete(old_asset.unique_name)
        except Exception as exc:
            current_app.logger.warning(
                f"Could not delete processed report asset during regeneration: {exc}"
            )
        db.session.delete(old_asset)

    # Reset processing state flags and dispatch the process_report chain
    record.celery_started = True
    record.celery_finished = None
    record.celery_failed = False

    celery = current_app.extensions["celery"]
    process = celery.tasks["app.tasks.process_report.process"]
    finalize = celery.tasks["app.tasks.process_report.finalize"]
    error = celery.tasks["app.tasks.process_report.error"]

    work = chain(process.si(record.id), finalize.si(record.id)).on_error(
        error.si(record.id, current_user.id)
    )
    work.apply_async()

    try:
        log_db_commit(
            "Cleared processed report and re-initiated processing for submission record",
            project_classes=record.owner.config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            "A database error was encountered while regenerating the processed report. Please contact an administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@documents.route("/launch_language_analysis/<int:sid>")
@login_required
def launch_language_analysis(sid):
    """Trigger the language analysis Celery workflow for a submission record."""
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    if record.report is None:
        flash(
            "Could not launch language analysis because no report has been uploaded for this submitter.",
            "info",
        )
        return redirect(redirect_url())

    if not is_deletable(record, message=True):
        return redirect(redirect_url())

    from ..tasks.llm_orchestration import enqueue_single_record

    try:
        enqueue_single_record(record.id, user=current_user, clear_existing=True)
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            "A database error was encountered while initiating language analysis. Please contact an administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@documents.route("/clear_language_analysis/<int:sid>")
@login_required
def clear_language_analysis(sid):
    """
    Clear stored language analysis results so analysis can be re-triggered.
    Also clears the processed report, since LLM outputs are now embedded in the cover page.
    """
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    if not is_deletable(record, message=True):
        return redirect(redirect_url())

    record.language_analysis = None
    record.language_analysis_started = False
    record.language_analysis_complete = False
    record.llm_analysis_failed = False
    record.llm_failure_reason = None
    record.llm_feedback_failed = None  # None = feedback not yet attempted on this run
    record.llm_feedback_failure_reason = None
    record.risk_factors = None

    # Clear the processed report since it embeds LLM outputs; it will be regenerated
    # automatically after analysis completes.
    if record.processed_report is not None:
        old_asset = record.processed_report
        record.processed_report_id = None
        record.celery_finished = False
        record.celery_failed = False
        # Delete the asset file from the object store
        try:
            object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
            from ..shared.cloud_object_store.base import ObjectStore

            store: ObjectStore = object_store
            if store is not None:
                store.delete(old_asset.unique_name)
        except Exception as exc:
            current_app.logger.warning(
                f"Could not delete processed report asset during analysis clear: {exc}"
            )
        db.session.delete(old_asset)

    try:
        log_db_commit(
            "Cleared language analysis results and processed report for submission record",
            project_classes=record.owner.config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            "A database error was encountered while clearing language analysis results. Please contact an administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@documents.route("/clear_llm_failure/<int:sid>")
@login_required
def clear_llm_failure(sid):
    """
    Clear the LLM failure flag for a submission record.
    For administrator use: allows the LLM submission step to be retried after
    a human has reviewed the raw response stored in the JSON blob.
    """
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    if not is_admin(current_user):
        flash("Only administrators can clear LLM failure flags.", "error")
        return redirect(redirect_url())

    record.llm_analysis_failed = False
    record.llm_failure_reason = None

    try:
        log_db_commit(
            "Cleared LLM failure flag for submission record",
            project_classes=record.owner.config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            "A database error was encountered while clearing the LLM failure flag. Please contact an administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@documents.route("/delete_submitter_report/<int:sid>")
@login_required
def delete_submitter_report(sid):
    # sid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    # nothing to do if no report attached
    if record.report is None:
        flash(
            "Could not delete report for this submitter because no report has been attached.",
            "info",
        )
        return redirect(redirect_url())

    # validate user has permission to carry out deletions
    if not is_deletable(record, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    title = "Delete project report"
    action_url = url_for(
        "documents.perform_delete_submitter_report", sid=sid, url=url, text=text
    )

    message = (
        "<p>Please confirm that you wish to remove the project report for "
        '<i class="fas fa-user-circle"></i> {student} {period}.</p>'
        "<p>This action cannot be undone.</p>".format(
            student=record.student_identifier["label"],
            period=record.period.display_name,
        )
    )
    submit_label = "Remove report"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@documents.route("/perform_delete_submitter_report/<int:sid>")
@login_required
def perform_delete_submitter_report(sid):
    # sid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    # nothing to do if no report attached
    if record.report is None:
        flash(
            "Could not delete report for this submitter because no file has been attached.",
            "info",
        )
        return redirect(redirect_url())

    # validate user has permission to carry out deletions
    if not is_deletable(record, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    try:
        # set lifetime of uploaded asset to 30 days, after which it will be deleted by the garbage collection.
        # also, unlink asset record from this SubmissionRecord.
        # notice we have to adjust the timestamp, since together with the lifetime this determines the expiry date
        expiry_date = datetime.now() + timedelta(days=30)

        record.report.expiry = expiry_date
        record.report_id = None

        # remove processed report if it has been generated
        if record.processed_report is not None:
            record.processed_report.expiry = expiry_date
            record.processed_report_id = None

        record.celery_started = None
        record.celery_finished = None
        record.timestamp = None

        record.turnitin_outcome = None
        record.turnitin_score = None
        record.turnitin_web_overlap = None
        record.turnitin_publication_overlap = None
        record.turnitin_student_overlap = None

        # remove exemplar flag
        record.report_exemplar = None

        log_db_commit(
            "Removed report from submission record",
            user=current_user,
            student=record.owner.student,
            project_classes=record.owner.config.project_class,
        )

    except SQLAlchemyError as e:
        flash(
            "Could not remove report from the submission record because of a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(
        url_for("documents.submitter_documents", sid=sid, url=url, text=text)
    )


@documents.route("/upload_submitter_report/<int:sid>", methods=["GET", "POST"])
@login_required
def upload_submitter_report(sid):
    # sid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    if record.report is not None:
        flash(
            "Can not upload a report for this submitter because an existing report is already attached.",
            "info",
        )
        return redirect(redirect_url())

    # check is convenor for the project's class, or has suitable admin/root privileges
    config: ProjectClassConfig = record.owner.config
    pclass: ProjectClass = config.project_class
    if not is_uploadable(
        record, message=True, allow_student=False, allow_faculty=False
    ):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    form = UploadReportForm(request.form)

    if form.validate_on_submit():
        if "report" in request.files:
            report_file = request.files["report"]

            # AssetUploadManager will populate most fields later
            asset = SubmittedAsset(
                timestamp=datetime.now(),
                uploaded_id=current_user.id,
                expiry=None,
                target_name=form.target_name.data,
                license=form.license.data,
            )
            db.session.add(asset)

            object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
            with AssetUploadManager(
                asset,
                data=report_file.stream.read(),
                storage=object_store,
                audit_data=f"upload_submitter_report (submission record id #{sid})",
                length=report_file.content_length,
                mimetype=report_file.content_type,
            ) as upload_mgr:
                pass

            try:
                db.session.flush()
            except SQLAlchemyError as e:
                db.session.rollback()
                flash(
                    "Could not upload report due to a database issue. Please contact an administrator.",
                    "error",
                )
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return redirect(
                    url_for("documents.submitter_documents", sid=record.sid)
                )

            dispatch_thumbnail_task(asset)

            # attach this asset as the uploaded report
            record.report_id = asset.id

            # uploading user has access
            asset.grant_user(current_user)

            # users with appropriate roles have access
            for role in record.roles:
                asset.grant_user(role.user)

            # student can download their own report
            if record.owner is not None and record.owner.student is not None:
                asset.grant_user(record.owner.student.user)

            # set up list of roles that should have access, if they exist
            asset.grant_roles(
                ["office", "convenor", "moderator", "exam_board", "external_examiner"]
            )

            # remove processed report, if that has not already been done
            if record.processed_report is not None:
                expiry_date = datetime.now() + timedelta(days=30)
                record.processed_report.expiry = expiry_date
                record.processed_report_id = None

            record.celery_started = True
            record.celery_finished = None
            record.timestamp = None
            record.report_exemplar = False

            try:
                log_db_commit(
                    "Uploaded report for submission record",
                    user=current_user,
                    student=record.owner.student,
                    project_classes=record.owner.config.project_class,
                )
            except SQLAlchemyError as e:
                db.session.rollback()
                flash(
                    "Could not upload report due to a database issue. Please contact an administrator.",
                    "error",
                )
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            else:
                flash(
                    'Report "{file}" was successfully uploaded.'.format(
                        file=report_file.filename
                    ),
                    "info",
                )

            # set up asynchronous task to process this report
            celery = current_app.extensions["celery"]

            process = celery.tasks["app.tasks.process_report.process"]
            finalize = celery.tasks["app.tasks.process_report.finalize"]
            error = celery.tasks["app.tasks.process_report.error"]

            work = chain(process.si(record.id), finalize.si(record.id)).on_error(
                error.si(record.id, current_user.id)
            )
            work.apply_async()

            return redirect(
                url_for("documents.submitter_documents", sid=sid, url=url, text=text)
            )

    else:
        if request.method == "GET":
            # default to 'Exam' license if one is available
            default_report_license = (
                db.session.query(AssetLicense).filter_by(abbreviation="Exam").first()
            )
            if default_report_license is None:
                default_report_license = current_user.default_license

            form.license.data = default_report_license

    return render_template_context(
        "documents/upload_report.html", record=record, form=form, url=url, text=text
    )


@documents.route("/pull_report_from_canvas/<int:rid>")
@login_required
def pull_report_from_canvas(rid):
    # rid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(rid)

    if record.report is not None:
        flash(
            "Can not upload a report for this submitter because an existing report is already attached.",
            "info",
        )
        return redirect(redirect_url())

    # check is convenor for the project's class, or has suitable admin/root privileges
    if not is_uploadable(
        record, message=True, allow_student=False, allow_faculty=False
    ):
        return redirect(redirect_url())

    url = request.args.get("url", None)

    # set up asynchronous task to pull this report
    celery = current_app.extensions["celery"]

    process = celery.tasks["app.tasks.canvas.pull_report"]
    finalize = celery.tasks["app.tasks.canvas.pull_report_finalize"]
    error = celery.tasks["app.tasks.canvas.pull_report_error"]

    work = chain(
        process.s(record.id, current_user.id), finalize.s(record.id, current_user.id)
    ).on_error(error.si(record.id, current_user.id))
    work.apply_async()

    if url:
        return redirect(url)

    return redirect(redirect_url())


@documents.route("/pull_all_reports_from_canvas/<int:pid>")
@roles_accepted("root", "admin", "faculty", "office")
def pull_all_reports_from_canvas(pid):
    # pid is a SubmissionPeriodRecord id
    period: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)

    config: ProjectClassConfig = period.config
    pclass: ProjectClass = config.project_class

    if not validate_is_convenor(pclass, allow_roles=["office"]):
        return redirect(redirect_url())

    # set up asynchronous task to pull this report
    celery = current_app.extensions["celery"]

    process = celery.tasks["app.tasks.canvas.pull_report"]
    finalize_batch = celery.tasks["app.tasks.canvas.pull_report_finalize_batch"]
    error = celery.tasks["app.tasks.canvas.pull_report_error"]
    summary = celery.tasks["app.tasks.canvas.pull_all_reports_summary"]

    available = (
        period.submissions.join(
            SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id
        )
        .filter(
            and_(
                SubmissionRecord.report_id == None,
                SubmissionRecord.canvas_submission_available.is_(True),
                SubmittingStudent.canvas_user_id != None,
            )
        )
        .all()
    )

    work = chord(
        [
            chain(
                process.s(record.id, None),
                finalize_batch.s(record.id, None).on_error(
                    error.si(record.id, current_user.id)
                ),
            )
            for record in available
        ],
        summary.s(current_user.id, period.id),
    )
    work.apply_async()

    return redirect(redirect_url())


@documents.route("/edit_submitter_report/<int:sid>", methods=["GET", "POST"])
@login_required
def edit_submitter_report(sid):
    # sid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    # get report asset; if none, nothing to do
    asset: SubmittedAsset = record.report
    if asset is None:
        flash(
            "Could not edit the report for this submission record because it has not yet been attached.",
            "info",
        )
        return redirect(redirect_url())

    # verify current user has privileges to edit the report
    if not is_editable(record, asset=asset, message=True, allow_student=False):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    form = EditReportForm(obj=asset)

    if form.validate_on_submit():
        asset.license = form.license.data
        asset.target_name = form.target_name.data

        # update processed report license to match
        if record.processed_report is not None:
            processed_asset: GeneratedAsset = record.processed_report
            processed_asset.license = form.license.data

        try:
            log_db_commit(
                "Saved changes to report asset record",
                user=current_user,
                student=record.owner.student,
                project_classes=record.owner.config.project_class,
            )
        except SQLAlchemyError as e:
            flash(
                "Could not save changes to this asset record due to a database error. Please contact a system administrator.",
                "error",
            )
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(
            url_for("documents.submitter_documents", sid=record.id, url=url, text=text)
        )

    action_url = url_for(
        "documents.edit_submitter_report", sid=record.id, url=url, text=text
    )
    return render_template_context(
        "documents/edit_attachment.html",
        form=form,
        record=record,
        asset=asset,
        action_url=action_url,
    )


@documents.route("/edit_submission_record_settings/<int:sid>", methods=["GET", "POST"])
@login_required
def edit_submission_record_settings(sid):
    # sid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    # verify current user has privileges to edit the record settings (admin/convenor only, not students)
    if not is_editable(record, message=True, allow_student=False):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    form = EditSubmissionRecordSettingsForm(obj=record)

    if form.validate_on_submit():
        record.report_exemplar = form.report_exemplar.data
        record.exemplar_comment = form.exemplar_comment.data
        record.report_secret = form.report_secret.data

        # if report_secret is set, clear the embargo date
        if form.report_secret.data:
            record.report_embargo = None
        else:
            record.report_embargo = form.report_embargo.data

        try:
            log_db_commit(
                "Saved changes to submission record settings",
                user=current_user,
                student=record.owner.student,
                project_classes=record.owner.config.project_class,
            )
        except SQLAlchemyError as e:
            flash(
                "Could not save changes to this submission record due to a database error. Please contact a system administrator.",
                "error",
            )
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(
            url_for("documents.submitter_documents", sid=record.id, url=url, text=text)
        )

    else:
        if request.method == "GET":
            form.report_secret.data = record.report_secret
            form.report_embargo.data = record.report_embargo
            form.report_exemplar.data = record.report_exemplar
            form.exemplar_comment.data = record.exemplar_comment

    action_url = url_for(
        "documents.edit_submission_record_settings", sid=record.id, url=url, text=text
    )
    return render_template_context(
        "documents/edit_submission_record_settings.html",
        form=form,
        record=record,
        action_url=action_url,
        url=url,
        text=text,
    )


@documents.route("/edit_submitter_attachment/<int:aid>", methods=["GET", "POST"])
@login_required
def edit_submitter_attachment(aid):
    # aid is a SubmissionAttachment
    attachment: SubmissionAttachment = SubmissionAttachment.query.get_or_404(aid)

    # get attached asset
    asset: SubmittedAsset = attachment.attachment
    if asset is None:
        flash(
            "Could not edit this attachment because of a database error. Please contact a system administrator.",
            "info",
        )
        return redirect(redirect_url())

    # extract SubmissionRecord and ensure that current user has sufficient privileges to perform edits
    record: SubmissionRecord = attachment.parent
    if not is_editable(record, asset=asset, message=True, allow_student=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    has_admin_rights = is_admin(current_user)
    EditSubmitterAttachmentForm = EditSubmitterAttachmentFormFactory(
        admin=has_admin_rights
    )
    form = EditSubmitterAttachmentForm(obj=attachment)

    if form.validate_on_submit():
        attachment.description = form.description.data

        asset.license = form.license.data
        asset.target_name = form.target_name.data

        if has_admin_rights:
            attachment.type = form.type.data
            selected_roles = form.roles.data
            attachment.set_roles(selected_roles)
            # reconcile student asset grant based on updated role set
            student_user = record.owner.student.user
            if SubmissionRoleTypesMixin.ROLE_STUDENT in selected_roles:
                if not asset.has_access(student_user):
                    asset.grant_user(student_user)
            else:
                if asset.in_user_acl(student_user):
                    asset.revoke_user(student_user)

        try:
            log_db_commit(
                "Saved changes to submitter attachment asset record",
                user=current_user,
                student=record.owner.student,
                project_classes=record.owner.config.project_class,
            )
        except SQLAlchemyError as e:
            flash(
                "Could not save changes to this asset record due to a database error. Please contact a system administrator.",
                "error",
            )
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(
            url_for("documents.submitter_documents", sid=record.id, url=url, text=text)
        )

    else:
        if request.method == "GET":
            form.license.data = asset.license
            form.target_name.data = asset.target_name
            if has_admin_rights:
                form.roles.data = list(attachment.role_set)

    action_url = url_for(
        "documents.edit_submitter_attachment", aid=attachment.id, url=url, text=text
    )
    return render_template_context(
        "documents/edit_attachment.html",
        form=form,
        record=record,
        attachment=attachment,
        asset=asset,
        action_url=action_url,
        has_admin_rights=has_admin_rights,
    )


@documents.route("/delete_submitter_attachment/<int:aid>")
@login_required
def delete_submitter_attachment(aid):
    # aid is a SubmissionAttachment id
    attachment: SubmissionAttachment = SubmissionAttachment.query.get_or_404(aid)

    # if asset is missing, nothing to do
    asset: SubmittedAsset = attachment.attachment
    if asset is None:
        flash(
            "Could not delete attachment because of a database error. Please contact a system administrator.",
            "info",
        )
        return redirect(redirect_url())

    record = attachment.parent
    if record is None:
        flash(
            "Can not delete this attachment because it is not attached to a submitter.",
            "info",
        )
        return redirect(redirect_url())

    if current_user.has_role("student") and not attachment.has_role_access(
        SubmissionRoleTypesMixin.ROLE_STUDENT
    ):
        # give no indication that this asset actually exists
        abort(404)

    # check user has sufficient privileges to perform the deletion
    if not is_deletable(record, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    title = "Delete project attachment"
    action_url = url_for(
        "documents.perform_delete_submitter_attachment",
        aid=aid,
        sid=record.id,
        url=url,
        text=text,
    )

    name = asset.target_name if asset.target_name is not None else asset.unique_name
    message = (
        "<p>Please confirm that you wish to remove the attachment <strong>{name}</strong> for "
        '<i class="fas fa-user-circle"></i> {student} {period}.</p>'
        "<p>This action cannot be undone.</p>".format(
            name=name,
            student=record.student_identifier["label"],
            period=record.period.display_name,
        )
    )
    submit_label = "Remove attachment"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@documents.route("/perform_delete_submitter_attachment/<int:aid>/<int:sid>")
@login_required
def perform_delete_submitter_attachment(aid, sid):
    # aid is a SubmissionAttachment id
    attachment = SubmissionAttachment.query.get_or_404(aid)

    # if asset is missing, nothing to do
    asset = attachment.attachment
    if asset is None:
        flash(
            "Could not delete attachment because of a database error. Please contact a system administrator.",
            "info",
        )
        return redirect(redirect_url())

    record = attachment.parent
    if record is None:
        flash(
            "Can not delete this attachment because it is not attached to a submitter.",
            "info",
        )
        return redirect(redirect_url())

    # check user has sufficient privileges to perform the deletion
    if not is_deletable(record, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    try:
        # set to delete in 30 days
        asset.expiry = datetime.now() + timedelta(days=30)
        attachment.attachment_id = None

        db.session.flush()

        db.session.delete(attachment)
        log_db_commit(
            "Deleted attachment from submission record",
            user=current_user,
            student=record.owner.student,
            project_classes=record.owner.config.project_class,
        )

    except SQLAlchemyError as e:
        flash(
            "Could not remove attachment from the submission record because of a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(
        url_for("documents.submitter_documents", sid=sid, url=url, text=text)
    )


@documents.route("/upload_submitter_attachment/<int:sid>", methods=["GET", "POST"])
@login_required
def upload_submitter_attachment(sid):
    # sid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    # check is convenor for the project's class, or has suitable admin/root privileges
    config = record.owner.config
    pclass = config.project_class
    if not is_uploadable(record, message=True, allow_student=True, allow_faculty=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    has_admin_rights = is_admin(current_user)
    UploadSubmitterAttachmentForm = UploadSubmitterAttachmentFormFactory(
        admin=has_admin_rights
    )
    form = UploadSubmitterAttachmentForm(request.form)

    if form.validate_on_submit():
        if "attachment" in request.files:
            attachment_file = request.files["attachment"]

            # AssetUploadManager will populate most fields later
            asset = SubmittedAsset(
                timestamp=datetime.now(),
                uploaded_id=current_user.id,
                expiry=None,
                target_name=form.target_name.data,
                license=form.license.data,
            )
            db.session.add(asset)

            object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
            with AssetUploadManager(
                asset,
                data=attachment_file.stream.read(),
                storage=object_store,
                audit_data=f"upload_submitter_attachment (submission record id #{sid})",
                length=attachment_file.content_length,
                mimetype=attachment_file.content_type,
            ) as upload_mgr:
                pass

            try:
                db.session.flush()
            except SQLAlchemyError as e:
                flash(
                    "Could not upload attachment due to a database issue. Please contact an administrator.",
                    "error",
                )
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return redirect(
                    url_for(
                        "documents.submitter_documents", sid=sid, url=url, text=text
                    )
                )

            dispatch_thumbnail_task(asset)

            # generate attachment record
            attachment = SubmissionAttachment(
                parent_id=record.id,
                attachment_id=asset.id,
                description=form.description.data,
            )

            if has_admin_rights:
                attachment.type = form.type.data
                selected_roles = form.roles.data
            else:
                attachment.type = SubmissionAttachment.ATTACHMENT_OTHER
                # non-admin uploads: student uploads are visible to students; others are unrestricted
                selected_roles = (
                    [SubmissionRoleTypesMixin.ROLE_STUDENT]
                    if current_user.has_role("student")
                    else []
                )

            # uploading user has access
            asset.grant_user(current_user)

            # users with submission roles have access
            for sr in record.roles:
                asset.grant_user(sr.user)

            # student access: user-based only — never grant_role("student")
            if SubmissionRoleTypesMixin.ROLE_STUDENT in selected_roles:
                asset.grant_user(record.owner.student.user)

            # broad role grants that always apply
            asset.grant_roles(
                ["office", "convenor", "moderator", "exam_board", "external_examiner"]
            )

            try:
                db.session.add(attachment)
                db.session.flush()
                attachment.set_roles(selected_roles)
                log_db_commit(
                    "Uploaded attachment for submission record",
                    user=current_user,
                    student=record.owner.student,
                    project_classes=pclass,
                )
            except SQLAlchemyError as e:
                flash(
                    "Could not upload attachment due to a database issue. Please contact an administrator.",
                    "error",
                )
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            else:
                flash(
                    'Attachment "{file}" was successfully uploaded.'.format(
                        file=attachment_file.filename
                    ),
                    "info",
                )

            return redirect(
                url_for("documents.submitter_documents", sid=sid, url=url, text=text)
            )

    else:
        if request.method == "GET":
            form.license.data = current_user.default_license

    return render_template_context(
        "documents/upload_attachment.html",
        record=record,
        form=form,
        url=url,
        text=text,
        has_admin_rights=has_admin_rights,
    )


def _get_attachment_asset(attach_type, attach_id):
    if attach_type == ATTACHMENT_TYPE_SUBMISSION:
        attachment: SubmissionAttachment = (
            db.session.query(SubmissionAttachment).filter_by(id=attach_id).first()
        )
        if attachment is None:
            raise KeyError

        asset: SubmittedAsset = attachment.attachment
        pclass: ProjectClass = attachment.parent.period.config.project_class

        return attachment, asset, pclass

    if attach_type == ATTACHMENT_TYPE_PERIOD:
        attachment: PeriodAttachment = PeriodAttachment.query.get_or_404(attach_id)
        if attachment is None:
            raise KeyError

        asset: SubmittedAsset = attachment.attachment
        pclass: ProjectClass = attachment.parent.config.project_class

        return attachment, asset, pclass

    if attach_type == ATTACHMENT_TYPE_UPLOADED_REPORT:
        record: SubmissionRecord = (
            db.session.query(SubmissionRecord).filter_by(id=attach_id).first()
        )
        if record is None:
            raise KeyError

        asset: SubmittedAsset = record.report
        pclass: ProjectClass = record.period.config.project_class

        return record, asset, pclass

    if attach_type == ATTACHMENT_TYPE_PROCESSED_REPORT:
        record: SubmissionRecord = (
            db.session.query(SubmissionRecord).filter_by(id=attach_id).first()
        )
        if record is None:
            return KeyError

        asset: GeneratedAsset = record.processed_report
        pclass: ProjectClass = record.period.config.project_class

        return record, asset, pclass

    if attach_type == ATTACHMENT_TYPE_FEEDBACK_REPORT:
        record: FeedbackReport = (
            db.session.query(FeedbackReport).filter_by(id=attach_id).first()
        )
        if record is None:
            raise KeyError

        asset: GeneratedAsset = record.asset
        pclass: ProjectClass = record.owner.period.config.project_class

        return record, asset, pclass

    raise KeyError


@documents.route("/attachment_acl/<int:attach_type>/<int:attach_id>")
@login_required
def attachment_acl(attach_type, attach_id):
    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for this project class
    if not validate_is_convenor(pclass, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)
    pane = request.args.get("pane", None)
    state_filter = request.args.get("state_filter", None)

    if pane not in ["users", "roles"]:
        pane = "users"

    if state_filter is None and session.get("documents_acl_state_filter"):
        state_filter = session["documents_acl_state_filter"]

    if state_filter not in ["all", "access", "no-access"]:
        # default to showing only users that have access
        state_filter = "access"

    if state_filter is not None:
        session["documents_acl_state_filter"] = state_filter

    return render_template_context(
        "documents/edit_acl.html",
        asset=asset,
        pclass_id=pclass.id,
        url=url,
        text=text,
        type=attach_type,
        attachment=attachment,
        pane=pane,
        state_filter=state_filter,
    )


@documents.route("/acl_user_ajax/<int:attach_type>/<int:attach_id>")
@login_required
def acl_user_ajax(attach_type, attach_id):
    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for this project class
    if not validate_is_convenor(pclass, message=True):
        return jsonify({})

    state_filter = request.args.get("state_filter", None)

    if state_filter not in ["all", "access", "no-access"]:
        state_filter = "all"

    user_list = db.session.query(User).filter_by(active=True).all()
    role_list = (
        db.session.query(Role)
        .filter(
            or_(Role.name == "faculty", Role.name == "student", Role.name == "office")
        )
        .all()
    )

    if state_filter == "access":
        user_list = [u for u in user_list if asset.has_access(u)]
    elif state_filter == "no-access":
        user_list = [u for u in user_list if not asset.has_access(u)]

    return ajax.documents.acl_user(user_list, role_list, asset, attachment, attach_type)


@documents.route("/acl_role_ajax/<int:attach_type>/<int:attach_id>")
@login_required
def acl_role_ajax(attach_type, attach_id):
    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for this project class
    if not validate_is_convenor(pclass, message=True):
        return jsonify({})

    state_filter = request.args.get("state_filter", None)

    if state_filter not in ["all", "access", "no-access"]:
        state_filter = "all"

    role_list = db.session.query(Role).all()

    if state_filter == "access":
        role_list = [r for r in role_list if asset.in_role_acl(r)]
    elif state_filter == "no-access":
        role_list = [r for r in role_list if not asset.in_role_acl(r)]

    return ajax.documents.acl_role(role_list, asset, attachment, attach_type)


@documents.route("/add_user_acl/<int:user_id>/<int:attach_type>/<int:attach_id>")
@login_required
def add_user_acl(user_id, attach_type, attach_id):
    # user_id identifies a user
    user = User.query.get_or_404(user_id)

    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for this project class
    if not validate_is_convenor(pclass, message=True):
        return redirect(redirect_url())

    try:
        asset.grant_user(user)
        log_db_commit(
            "Granted user access to asset",
            user=current_user,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not grant access to this asset due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@documents.route("/remove_user_acl/<int:user_id>/<int:attach_type>/<int:attach_id>")
@login_required
def remove_user_acl(user_id, attach_type, attach_id):
    # user_id identifies a user
    user = User.query.get_or_404(user_id)

    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for this project class
    if not validate_is_convenor(pclass, message=True):
        return redirect(redirect_url())

    try:
        asset.revoke_user(user)
        log_db_commit(
            "Revoked user access to asset",
            user=current_user,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not remove access to this asset due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@documents.route("/add_role_acl/<int:role_id>/<int:attach_type>/<int:attach_id>")
@login_required
def add_role_acl(role_id, attach_type, attach_id):
    # role_id identifies a Role
    role = Role.query.get_or_404(role_id)

    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for this project class
    if not validate_is_convenor(pclass, message=True):
        return redirect(redirect_url())

    try:
        asset.grant_role(role)
        log_db_commit(
            "Granted role-based access to asset",
            user=current_user,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not grant role-based access to this asset due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@documents.route("/remove_role_acl/<int:role_id>/<int:attach_type>/<int:attach_id>")
@login_required
def remove_role_acl(role_id, attach_type, attach_id):
    # role_id identifies a Role
    role = Role.query.get_or_404(role_id)

    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for this project class
    if not validate_is_convenor(pclass, message=True):
        return redirect(redirect_url())

    try:
        asset.revoke_role(role)
        log_db_commit(
            "Revoked role-based access to asset",
            user=current_user,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not remove role-based access to this asset due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@documents.route("/attachment_download_log/<int:attach_type>/<int:attach_id>")
@login_required
def attachment_download_log(attach_type, attach_id):
    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for ths project class
    if not validate_is_convenor(pclass, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    return render_template_context(
        "documents/download_log.html",
        asset=asset,
        pclass_id=pclass.id,
        url=url,
        text=text,
        type=attach_type,
        attachment=attachment,
    )


@documents.route("/download_log_ajax/<int:attach_type>/<int:attach_id>")
@login_required
def download_log_ajax(attach_type, attach_id):
    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for ths project class
    if not validate_is_convenor(pclass, message=True):
        return jsonify({})

    return ajax.documents.download_log(asset.downloads.all())


_THUMBNAIL_ASSET_TYPES = {
    "GeneratedAsset": GeneratedAsset,
    "SubmittedAsset": SubmittedAsset,
}


@documents.route("/thumbnail/<string:asset_type>/<int:asset_id>/<string:size>")
@login_required
def serve_thumbnail(asset_type, asset_id, size):
    if asset_type not in _THUMBNAIL_ASSET_TYPES:
        abort(404)

    model_class = _THUMBNAIL_ASSET_TYPES[asset_type]
    parent = db.session.query(model_class).filter_by(id=asset_id).first()
    if parent is None:
        abort(404)

    if not parent.has_access(current_user):
        abort(403)

    if size == "small":
        thumbnail: ThumbnailAsset = parent.small_thumbnail
    elif size == "medium":
        thumbnail: ThumbnailAsset = parent.medium_thumbnail
    else:
        abort(404)

    if thumbnail is None or thumbnail.lost:
        abort(404)

    bucket_map = current_app.config.get("OBJECT_STORAGE_BUCKETS")
    thumbnails_store = bucket_map.get(buckets.THUMBNAILS_BUCKET)
    if thumbnails_store is None:
        abort(503)

    url = thumbnails_store.get_url(
        thumbnail.unique_name,
        audit_data=f"documents.serve_thumbnail ({asset_type} #{asset_id}, {size})",
    )

    r = http_requests.get(url, stream=True)
    if not r.ok:
        abort(r.status_code)

    content_type = thumbnail.mimetype or "image/jpeg"
    return Response(
        stream_with_context(r.iter_content(chunk_size=8192)),
        content_type=content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


def _build_lexical_gauge(metrics_data) -> tuple:
    """
    Build a Bokeh Column layout containing three horizontal gauge figures for MATTR, MTLD,
    and Burstiness.  Returns (div, script) from bokeh.embed.components, or (None, None) if
    metrics_data is None or all three metric values are absent.
    """
    if metrics_data is None:
        return None, None

    _flag_color = {"ok": "#198754", "note": "#ffc107", "strong": "#dc3545"}

    def _gauge_fig(
        label, value, low, high, threshold, flag, fmt=".3f",
        high_threshold=None, strong_threshold=None
    ):
        if value is None:
            return None

        # Clamp the displayed value to the axis range
        display_val = max(low, min(high, value))
        flag_col = _flag_color.get(flag, "#6c757d")

        p = figure(
            width=480,
            height=80,
            x_range=(low, high),
            y_range=(-1, 1),
            toolbar_location=None,
        )
        p.sizing_mode = "fixed"
        p.background_fill_color = None
        p.border_fill_color = None
        p.outline_line_color = None
        p.axis.visible = False
        p.xgrid.visible = False
        p.ygrid.visible = False
        p.toolbar.logo = None

        # Background track
        p.quad(left=low, right=high, bottom=-0.35, top=0.35,
               fill_color="#e9ecef", line_color=None)

        if high_threshold is None:
            # ── Single-threshold mode (MATTR, Burstiness) ──────────────────
            # With strong_threshold: three zones (strong / note / safe).
            # Without strong_threshold: two zones (concern / safe), flag-colored.
            if strong_threshold is not None:
                p.quad(left=low, right=strong_threshold, bottom=-0.35, top=0.35,
                       fill_color="#f8d7da", line_color=None)
                p.quad(left=strong_threshold, right=threshold, bottom=-0.35, top=0.35,
                       fill_color="#fff3cd", line_color=None)
                p.quad(left=threshold, right=high, bottom=-0.35, top=0.35,
                       fill_color="#d1e7dd", line_color=None)
                # Strong threshold line (red dashed)
                p.add_layout(Span(location=strong_threshold, dimension="height",
                                  line_color="#dc3545", line_dash="dashed", line_width=1.5))
                # Note threshold line (grey dashed)
                p.add_layout(Span(location=threshold, dimension="height",
                                  line_color="#495057", line_dash="dashed", line_width=1.5))
                # Labels: min and max on the outer row; note and strong labels staggered
                p.add_layout(Label(x=low, y=-0.38, x_units="data", y_units="data",
                                   text=f"{low:{fmt}}", text_font_size="9px",
                                   text_color="#6c757d", text_align="left",
                                   text_baseline="top", background_fill_alpha=0))
                p.add_layout(Label(x=high, y=-0.38, x_units="data", y_units="data",
                                   text=f"{high:{fmt}}", text_font_size="9px",
                                   text_color="#6c757d", text_align="right",
                                   text_baseline="top", background_fill_alpha=0))
                p.add_layout(Label(x=threshold, y=-0.38, x_units="data", y_units="data",
                                   text=f"note {threshold:{fmt}}", text_font_size="9px",
                                   text_color="#495057", text_align="center",
                                   text_baseline="top", background_fill_alpha=0))
                p.add_layout(Label(x=strong_threshold, y=-0.62, x_units="data", y_units="data",
                                   text=f"strong {strong_threshold:{fmt}}", text_font_size="9px",
                                   text_color="#dc3545", text_align="center",
                                   text_baseline="top", background_fill_alpha=0))
            else:
                concern_col = (
                    "#f8d7da" if flag == "strong"
                    else "#fff3cd" if flag == "note"
                    else "#d1e7dd"
                )
                p.quad(left=low, right=threshold, bottom=-0.35, top=0.35,
                       fill_color=concern_col, line_color=None)
                p.quad(left=threshold, right=high, bottom=-0.35, top=0.35,
                       fill_color="#d1e7dd", line_color=None)
                p.add_layout(Span(location=threshold, dimension="height",
                                  line_color="#495057", line_dash="dashed", line_width=1.5))
                p.add_layout(Label(x=low, y=-0.38, x_units="data", y_units="data",
                                   text=f"{low:{fmt}}", text_font_size="9px",
                                   text_color="#6c757d", text_align="left",
                                   text_baseline="top", background_fill_alpha=0))
                p.add_layout(Label(x=threshold, y=-0.38, x_units="data", y_units="data",
                                   text=f"threshold {threshold:{fmt}}", text_font_size="9px",
                                   text_color="#495057", text_align="center",
                                   text_baseline="top", background_fill_alpha=0))
                p.add_layout(Label(x=high, y=-0.38, x_units="data", y_units="data",
                                   text=f"{high:{fmt}}", text_font_size="9px",
                                   text_color="#6c757d", text_align="right",
                                   text_baseline="top", background_fill_alpha=0))
        else:
            # ── Two-threshold (band) mode (MTLD) ────────────────────────────
            # With strong_threshold: lower concern area is split into strong/note zones.
            # Upper concern area is always note-level (no upper strong threshold defined).
            if strong_threshold is not None:
                p.quad(left=low, right=strong_threshold, bottom=-0.35, top=0.35,
                       fill_color="#f8d7da", line_color=None)
                p.quad(left=strong_threshold, right=threshold, bottom=-0.35, top=0.35,
                       fill_color="#fff3cd", line_color=None)
            else:
                p.quad(left=low, right=threshold, bottom=-0.35, top=0.35,
                       fill_color="#f8d7da", line_color=None)
            p.quad(left=threshold, right=high_threshold, bottom=-0.35, top=0.35,
                   fill_color="#d1e7dd", line_color=None)
            p.quad(left=high_threshold, right=high, bottom=-0.35, top=0.35,
                   fill_color="#fff3cd", line_color=None)

            if strong_threshold is not None:
                p.add_layout(Span(location=strong_threshold, dimension="height",
                                  line_color="#dc3545", line_dash="dashed", line_width=1.5))
            p.add_layout(Span(location=threshold, dimension="height",
                              line_color="#495057", line_dash="dashed", line_width=1.5))
            p.add_layout(Span(location=high_threshold, dimension="height",
                              line_color="#495057", line_dash="dashed", line_width=1.5))

            p.add_layout(Label(x=low, y=-0.38, x_units="data", y_units="data",
                               text=f"{low:{fmt}}", text_font_size="9px",
                               text_color="#6c757d", text_align="left",
                               text_baseline="top", background_fill_alpha=0))
            p.add_layout(Label(x=threshold, y=-0.38, x_units="data", y_units="data",
                               text=f"low {threshold:{fmt}}", text_font_size="9px",
                               text_color="#495057", text_align="center",
                               text_baseline="top", background_fill_alpha=0))
            p.add_layout(Label(x=high_threshold, y=-0.38, x_units="data", y_units="data",
                               text=f"high {high_threshold:{fmt}}", text_font_size="9px",
                               text_color="#495057", text_align="center",
                               text_baseline="top", background_fill_alpha=0))
            p.add_layout(Label(x=high, y=-0.38, x_units="data", y_units="data",
                               text=f"{high:{fmt}}", text_font_size="9px",
                               text_color="#6c757d", text_align="right",
                               text_baseline="top", background_fill_alpha=0))
            if strong_threshold is not None:
                p.add_layout(Label(x=strong_threshold, y=-0.62, x_units="data", y_units="data",
                                   text=f"strong {strong_threshold:{fmt}}", text_font_size="9px",
                                   text_color="#dc3545", text_align="center",
                                   text_baseline="top", background_fill_alpha=0))

        # Metric name label (shared)
        p.add_layout(Label(x=low, y=0, x_units="data", y_units="data",
                           text=label, text_font_size="11px", text_font_style="bold",
                           text_align="left", text_baseline="middle",
                           x_offset=2, y_offset=0, background_fill_alpha=0))

        # Value marker
        p.circle(x=[display_val], y=[0], size=14,
                 fill_color=flag_col, line_color="white", line_width=1.5)

        # Current value label above marker
        p.add_layout(Label(x=display_val, y=0.5, x_units="data", y_units="data",
                           text=f"{value:{fmt}}", text_font_size="10px",
                           text_color=flag_col, text_font_style="bold",
                           text_align="center", text_baseline="bottom",
                           background_fill_alpha=0))
        return p

    def _symmetric_gauge_fig(
        label, value, low, high,
        strong_low, note_low, note_high, strong_high,
        flag, fmt=".3f"
    ):
        """
        Five-zone symmetric gauge: strong-low / note-low / ok / note-high / strong-high.
        Used for Burstiness B and sentence CV, which have concern zones on both sides.
        """
        if value is None:
            return None

        display_val = max(low, min(high, value))
        flag_col = _flag_color.get(flag, "#6c757d")

        p = figure(
            width=480,
            height=90,
            x_range=(low, high),
            y_range=(-1, 1),
            toolbar_location=None,
        )
        p.sizing_mode = "fixed"
        p.background_fill_color = None
        p.border_fill_color = None
        p.outline_line_color = None
        p.axis.visible = False
        p.xgrid.visible = False
        p.ygrid.visible = False
        p.toolbar.logo = None

        # Background track
        p.quad(left=low, right=high, bottom=-0.35, top=0.35,
               fill_color="#e9ecef", line_color=None)

        # Five colour zones
        p.quad(left=low, right=strong_low, bottom=-0.35, top=0.35,
               fill_color="#f8d7da", line_color=None)
        p.quad(left=strong_low, right=note_low, bottom=-0.35, top=0.35,
               fill_color="#fff3cd", line_color=None)
        p.quad(left=note_low, right=note_high, bottom=-0.35, top=0.35,
               fill_color="#d1e7dd", line_color=None)
        p.quad(left=note_high, right=strong_high, bottom=-0.35, top=0.35,
               fill_color="#fff3cd", line_color=None)
        p.quad(left=strong_high, right=high, bottom=-0.35, top=0.35,
               fill_color="#f8d7da", line_color=None)

        # Boundary lines
        p.add_layout(Span(location=strong_low, dimension="height",
                          line_color="#dc3545", line_dash="dashed", line_width=1.5))
        p.add_layout(Span(location=note_low, dimension="height",
                          line_color="#495057", line_dash="dashed", line_width=1.5))
        p.add_layout(Span(location=note_high, dimension="height",
                          line_color="#495057", line_dash="dashed", line_width=1.5))
        p.add_layout(Span(location=strong_high, dimension="height",
                          line_color="#dc3545", line_dash="dashed", line_width=1.5))

        # Labels: outer bounds at row -0.38; note lines at row -0.38; strong lines at row -0.62
        p.add_layout(Label(x=low, y=-0.38, x_units="data", y_units="data",
                           text=f"{low:{fmt}}", text_font_size="9px",
                           text_color="#6c757d", text_align="left",
                           text_baseline="top", background_fill_alpha=0))
        p.add_layout(Label(x=high, y=-0.38, x_units="data", y_units="data",
                           text=f"{high:{fmt}}", text_font_size="9px",
                           text_color="#6c757d", text_align="right",
                           text_baseline="top", background_fill_alpha=0))
        p.add_layout(Label(x=note_low, y=-0.38, x_units="data", y_units="data",
                           text=f"note {note_low:{fmt}}", text_font_size="9px",
                           text_color="#495057", text_align="center",
                           text_baseline="top", background_fill_alpha=0))
        p.add_layout(Label(x=note_high, y=-0.38, x_units="data", y_units="data",
                           text=f"note {note_high:{fmt}}", text_font_size="9px",
                           text_color="#495057", text_align="center",
                           text_baseline="top", background_fill_alpha=0))
        p.add_layout(Label(x=strong_low, y=-0.62, x_units="data", y_units="data",
                           text=f"strong {strong_low:{fmt}}", text_font_size="9px",
                           text_color="#dc3545", text_align="center",
                           text_baseline="top", background_fill_alpha=0))
        p.add_layout(Label(x=strong_high, y=-0.62, x_units="data", y_units="data",
                           text=f"strong {strong_high:{fmt}}", text_font_size="9px",
                           text_color="#dc3545", text_align="center",
                           text_baseline="top", background_fill_alpha=0))

        # Metric name label
        p.add_layout(Label(x=low, y=0, x_units="data", y_units="data",
                           text=label, text_font_size="11px", text_font_style="bold",
                           text_align="left", text_baseline="middle",
                           x_offset=2, y_offset=0, background_fill_alpha=0))

        # Value marker
        p.circle(x=[display_val], y=[0], size=14,
                 fill_color=flag_col, line_color="white", line_width=1.5)

        # Current value label above marker
        p.add_layout(Label(x=display_val, y=0.5, x_units="data", y_units="data",
                           text=f"{value:{fmt}}", text_font_size="10px",
                           text_color=flag_col, text_font_style="bold",
                           text_align="center", text_baseline="bottom",
                           background_fill_alpha=0))
        return p

    mattr_m = metrics_data.get("mattr", {})
    mtld_m = metrics_data.get("mtld", {})
    burst_m = metrics_data.get("burstiness", {})
    cv_m = metrics_data.get("sentence_cv", {})

    figs = []
    # MATTR: two-sided (low strong / low note / ok / high note); reuse existing two-threshold mode
    f = _gauge_fig(
        "MATTR",
        mattr_m.get("value"),
        0.0,
        1.0,
        MATTR_NOTE_LOW_THRESHOLD,
        mattr_m.get("flag", "ok"),
        fmt=".3f",
        high_threshold=MATTR_NOTE_HIGH_THRESHOLD,
        strong_threshold=MATTR_STRONG_THRESHOLD,
    )
    if f:
        figs.append(f)
    f = _gauge_fig(
        "MTLD",
        mtld_m.get("value"),
        0.0,
        130.0,
        MTLD_NOTE_THRESHOLD,
        mtld_m.get("flag", "ok"),
        fmt=".1f",
        high_threshold=MTLD_HIGH_NOTE_THRESHOLD,
        strong_threshold=MTLD_STRONG_THRESHOLD,
    )
    if f:
        figs.append(f)
    f = _symmetric_gauge_fig(
        "Burstiness (B)",
        burst_m.get("value"),
        -1.0,
        1.0,
        strong_low=BURSTINESS_STRONG_LOW,
        note_low=BURSTINESS_NOTE_LOW,
        note_high=BURSTINESS_NOTE_HIGH,
        strong_high=BURSTINESS_STRONG_HIGH,
        flag=burst_m.get("flag", "ok"),
        fmt=".3f",
    )
    if f:
        figs.append(f)
    f = _symmetric_gauge_fig(
        "Sentence CV",
        cv_m.get("value"),
        0.0,
        1.5,
        strong_low=SENT_CV_STRONG_LOW,
        note_low=SENT_CV_NOTE_LOW,
        note_high=SENT_CV_NOTE_HIGH,
        strong_high=SENT_CV_STRONG_HIGH,
        flag=cv_m.get("flag", "ok"),
        fmt=".3f",
    )
    if f:
        figs.append(f)

    if not figs:
        return None, None

    layout = column(*figs, sizing_mode="fixed", spacing=8)
    script, div = components(layout)
    return div, script


def _build_document_length_gauge(la_metrics: dict, config) -> tuple:
    """
    Build Bokeh gauge figure(s) for word count and/or page count versus configured limits.
    Returns (div, script) or (None, None) if no limits are enabled or no measurements available.

    la_metrics: the 'metrics' sub-dict from record.language_analysis_data
    config:     ProjectClassConfig (for effective_word_limit_enabled etc.)
    """
    if config is None or not la_metrics:
        return None, None

    _ok_col = "#198754"
    _bad_col = "#dc3545"

    def _gauge_fig(label, measured, limit):
        if measured is None or limit is None or limit <= 0:
            return None

        flag_col = _ok_col if measured <= limit else _bad_col
        high = max(limit * 1.5, measured * 1.1)
        display_val = min(float(measured), high)

        p = figure(
            width=480,
            height=55,
            x_range=(0, high),
            y_range=(-1, 1),
            toolbar_location=None,
        )
        p.sizing_mode = "fixed"
        p.background_fill_color = None
        p.border_fill_color = None
        p.outline_line_color = None
        p.axis.visible = False
        p.xgrid.visible = False
        p.ygrid.visible = False
        p.toolbar.logo = None

        # Background track
        p.quad(
            left=0,
            right=high,
            bottom=-0.35,
            top=0.35,
            fill_color="#e9ecef",
            line_color=None,
        )
        # Safe zone (0 → limit) — always green
        p.quad(
            left=0,
            right=float(limit),
            bottom=-0.35,
            top=0.35,
            fill_color="#d1e7dd",
            line_color=None,
        )
        # Concern zone (limit → high) — always red
        p.quad(
            left=float(limit),
            right=high,
            bottom=-0.35,
            top=0.35,
            fill_color="#f8d7da",
            line_color=None,
        )

        # Limit marker
        p.add_layout(
            Span(
                location=float(limit),
                dimension="height",
                line_color="#495057",
                line_dash="dashed",
                line_width=1.5,
            )
        )

        # Value marker
        p.circle(
            x=[display_val],
            y=[0],
            size=14,
            fill_color=flag_col,
            line_color="white",
            line_width=1.5,
        )

        # Labels: metric name, 0, limit, max, current value
        p.add_layout(
            Label(
                x=0,
                y=0,
                x_units="data",
                y_units="data",
                text=label,
                text_font_size="11px",
                text_font_style="bold",
                text_align="left",
                text_baseline="middle",
                x_offset=2,
                y_offset=0,
                background_fill_alpha=0,
            )
        )
        p.add_layout(
            Label(
                x=0,
                y=-0.38,
                x_units="data",
                y_units="data",
                text="0",
                text_font_size="9px",
                text_color="#6c757d",
                text_align="left",
                text_baseline="top",
                background_fill_alpha=0,
            )
        )
        p.add_layout(
            Label(
                x=float(limit),
                y=-0.38,
                x_units="data",
                y_units="data",
                text=f"limit {limit:,.0f}",
                text_font_size="9px",
                text_color="#495057",
                text_align="center",
                text_baseline="top",
                background_fill_alpha=0,
            )
        )
        p.add_layout(
            Label(
                x=high,
                y=-0.38,
                x_units="data",
                y_units="data",
                text=f"{high:,.0f}",
                text_font_size="9px",
                text_color="#6c757d",
                text_align="right",
                text_baseline="top",
                background_fill_alpha=0,
            )
        )
        p.add_layout(
            Label(
                x=display_val,
                y=0.5,
                x_units="data",
                y_units="data",
                text=f"{measured:,.0f}",
                text_font_size="10px",
                text_color=flag_col,
                text_font_style="bold",
                text_align="center",
                text_baseline="bottom",
                background_fill_alpha=0,
            )
        )
        return p

    figs = []
    if config.effective_word_limit_enabled and config.effective_word_limit:
        f = _gauge_fig(
            "Words", la_metrics.get("word_count"), config.effective_word_limit
        )
        if f:
            figs.append(f)
    if config.effective_page_limit_enabled and config.effective_page_limit:
        f = _gauge_fig(
            "Pages", la_metrics.get("page_count"), config.effective_page_limit
        )
        if f:
            figs.append(f)

    if not figs:
        return None, None

    layout = column(*figs, sizing_mode="fixed", spacing=8)
    script, div = components(layout)
    return div, script


@documents.route("/llm-report/<int:record_id>")
@login_required
def llm_report(record_id):
    """
    Display the full LLM language analysis report for a SubmissionRecord.
    Accessible from the convenor submitters inspector and the submitter manager view.
    """
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(record_id)
    period: SubmissionPeriodRecord = record.period
    pclass: ProjectClass = period.config.project_class

    # Access control: convenors, admin, root, office, or the submitting student's supervisors
    # and markers all need to be able to access this.
    allowed = (
        current_user.has_role("root")
        or current_user.has_role("admin")
        or current_user.has_role("office")
        or pclass.is_convenor(current_user.id)
    )
    if not allowed:
        # Check if the current user has a role on this submission
        for role in record.roles:
            if role.user_id == current_user.id:
                allowed = True
                break
    if not allowed:
        abort(403)

    url = request.args.get(
        "url", url_for("documents.submitter_documents", sid=record.owner_id, url="/")
    )
    text = request.args.get("text", "Back")

    la = record.language_analysis_data
    llm_result = la.get("llm_result", {})
    llm_feedback = la.get("llm_feedback", {})
    criterion_map = la.get("criterion_map", {})
    errors = la.get("errors", [])

    # Prepare Python-side display data — keeps Jinja2 templates free of business logic
    metrics_data = (
        record.llm_metrics_for_display() if record.language_analysis_complete else None
    )
    rf_summary = record.risk_factors_ui_summary()
    rf_items = record.risk_factor_display_items()

    # Resolve display URL for the risk factors resolution view
    resolve_url = url_for(
        "convenor.resolve_risk_factors",
        record_id=record.id,
        url=request.url,
        text="LLM Report",
    )

    # Admin-only actions: can clear results or clear and re-run
    can_admin = current_user.has_role("root") or current_user.has_role("admin")

    gauge_div, gauge_script = _build_lexical_gauge(metrics_data)

    la_metrics = la.get("metrics", {})
    length_gauge_div, length_gauge_script = _build_document_length_gauge(
        la_metrics, period.config
    )

    return render_template_context(
        "documents/llm_report.html",
        record=record,
        period=period,
        pclass=pclass,
        llm_result=llm_result,
        llm_feedback=llm_feedback,
        criterion_map=criterion_map,
        errors=errors,
        metrics_data=metrics_data,
        rf_summary=rf_summary,
        rf_items=rf_items,
        resolve_url=resolve_url,
        can_admin=can_admin,
        gauge_div=gauge_div,
        gauge_script=gauge_script,
        length_gauge_div=length_gauge_div,
        length_gauge_script=length_gauge_script,
        url=url,
        text=text,
    )


@documents.route("/analysis_status/<int:sid>")
@login_required
def analysis_status(sid):
    """
    Lightweight status endpoint used by client-side JS to poll for analysis completion.
    Returns JSON {"status": "in_progress"|"complete"|"failed"|"not_started"}.
    """
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)
    if record.language_analysis_complete:
        status = "complete"
    elif record.llm_analysis_failed:
        status = "failed"
    elif record.language_analysis_started:
        status = "in_progress"
    else:
        status = "not_started"
    return jsonify({"status": status})
