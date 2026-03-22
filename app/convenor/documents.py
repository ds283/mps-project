#
# Created by David Seery on 24/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from datetime import date, datetime, timedelta
from functools import partial
from typing import List, Optional, Tuple
from uuid import uuid4

import parse
from celery import chain
from celery.result import AsyncResult
from dateutil import parser
from dateutil.relativedelta import relativedelta
from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)
from flask_security import current_user, roles_accepted
from ordered_set import OrderedSet
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import class_mapper, with_polymorphic
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.sql import func, literal_column

import app.ajax as ajax

from ..admin.forms import EditEmailTemplateForm, LevelSelectorForm
from ..admin.views import create_new_email_template_labels
from ..database import db
from ..documents.forms import EditPeriodAttachmentForm, UploadPeriodAttachmentForm
from ..faculty.forms import (
    AddDescriptionFormFactory,
    AddProjectFormFactory,
    EditDescriptionContentForm,
    EditDescriptionSettingsFormFactory,
    EditProjectFormFactory,
    MoveDescriptionFormFactory,
    PresentationFeedbackForm,
    SkillSelectorForm,
    SubmissionRoleFeedbackForm,
    SubmissionRoleResponseForm,
)
from ..models import (
    BackupRecord,
    Bookmark,
    ConfirmRequest,
    ConvenorGenericTask,
    ConvenorSelectorTask,
    ConvenorSubmitterTask,
    ConvenorTask,
    CustomOffer,
    DegreeProgramme,
    DegreeType,
    EmailTemplate,
    EnrollmentRecord,
    FacultyData,
    FeedbackRecipe,
    FeedbackReport,
    FHEQ_Level,
    FilterRecord,
    GeneratedAsset,
    LiveProject,
    LiveProjectAlternative,
    MatchingRecord,
    MatchingRole,
    Module,
    PeriodAttachment,
    PopularityRecord,
    PresentationFeedback,
    Project,
    ProjectAlternative,
    ProjectClass,
    ProjectClassConfig,
    ProjectDescription,
    ResearchGroup,
    SelectingStudent,
    SelectionRecord,
    SkillGroup,
    StudentData,
    SubmissionPeriodRecord,
    SubmissionPeriodUnit,
    SubmissionRecord,
    SubmissionRole,
    SubmittedAsset,
    SubmittingStudent,
    SupervisionEvent,
    SupervisionEventTemplate,
    Tenant,
    TransferableSkill,
    User,
    WorkflowMixin,
)
from ..projecthub.forms import ReassignEventOwnerFormFactory
from ..shared.actions import do_cancel_confirm, do_confirm, do_deconfirm_to_pending
from ..shared.asset_tools import AssetUploadManager
from ..shared.context.convenor_dashboard import (
    build_convenor_tasks_query,
    get_capacity_data,
    get_convenor_approval_data,
    get_convenor_dashboard_data,
    get_convenor_todo_data,
)
from ..shared.context.global_context import render_template_context
from ..shared.convenor import (
    add_blank_submitter,
    add_liveproject,
    add_selector,
    build_outstanding_confirmations_query,
)
from ..shared.conversions import is_integer
from ..shared.forms.forms import SelectSubmissionRecordFormFactory
from ..shared.projects import (
    create_new_tags,
    get_filter_list_for_groups_and_skills,
    project_list_in_memory_handler,
    project_list_SQL_handler,
)
from ..shared.quickfixes import (
    QUICKFIX_POPULATE_SELECTION_FROM_BOOKMARKS_AVAILABLE,
    QUICKFIX_POPULATE_SELECTION_FROM_BOOKMARKS_UNAVAILABLE,
)
from ..shared.security import validate_nonce
from ..shared.sqlalchemy import clone_model, get_count
from ..shared.utils import (
    build_enrol_selector_candidates,
    build_enrol_submitter_candidates,
    build_submitters_data,
    filter_assessors,
    get_convenor_filter_record,
    get_current_year,
    home_dashboard,
    home_dashboard_url,
    redirect_url,
)
from ..shared.validators import (
    validate_assign_feedback,
    validate_edit_description,
    validate_edit_project,
    validate_is_admin_or_convenor,
    validate_is_administrator,
    validate_is_convenor,
    validate_project_class,
    validate_project_open,
    validate_view_project,
)
from ..student.actions import store_selection
from ..task_queue import register_task
from ..tools import ServerSideInMemoryHandler, ServerSideSQLHandler
from ..tools.ServerSideProcessing import FakeQuery
from app.convenor import convenor
from .forms import (
    AddConvenorGenericTask,
    AddConvenorStudentTask,
    AddSubmissionPeriodUnitFormFactory,
    AddSubmitterRoleForm,
    AddSupervisionEventTemplateFormFactory,
    AssignPresentationFeedbackFormFactory,
    ChangeDeadlineFormFactory,
    CreateCustomOfferFormFactory,
    CustomCATSLimitForm,
    DuplicateProjectFormFactory,
    EditConvenorGenericTask,
    EditConvenorStudentTask,
    EditCustomOfferFormFactory,
    EditLiveProjectAlternativeForm,
    EditLiveProjectSupervisorsFactory,
    EditPeriodRecordFormFactory,
    EditProjectAlternativeForm,
    EditProjectConfigFormFactory,
    EditProjectSupervisorsFactory,
    EditRolesFormFactory,
    EditSubmissionPeriodRecordPresentationsForm,
    EditSubmissionPeriodUnitFormFactory,
    EditSubmissionRoleForm,
    EditSupervisionEventTemplateFormFactory,
    GoLiveFormFactory,
    IssueFacultyConfirmRequestFormFactory,
    ManualAssignFormFactory,
    OpenFeedbackFormFactory,
    TestOpenFeedbackForm,
)


@convenor.route("/update_CATS/<int:config_id>")
@roles_accepted("faculty", "admin", "root")
def update_CATS(config_id):
    # id identifies a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(config_id)
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    config.CATS_supervision = config.project_class.CATS_supervision
    config.CATS_marking = config.project_class.CATS_marking
    config.CATS_moderation = config.project_class.CATS_moderation
    config.CATS_presentation = config.project_class.CATS_presentation

    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/force_convert_bookmarks/<int:sel_id>")
@roles_accepted("faculty", "admin", "root")
def force_convert_bookmarks(sel_id):
    # sel_id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sel_id)

    converted_status = bool(int(request.args.get("converted", "1")))
    no_submit_IP = bool(int(request.args.get("no_submit_IP", "1")))
    force = bool(int(request.args.get("force", "0")))
    reset = bool(int(request.args.get("reset", "1")))
    force_unavailable = bool(int(request.args.get("force_unavailable", "0")))

    # reject user if not a suitable convenor or administrator
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    if (
            sel.config.selector_lifecycle
            < ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN
    ):
        flash(
            "Forced conversion of bookmarks can be performed only after project selection is open.",
            "info",
        )
        return redirect(redirect_url())

    if not force and sel.has_submitted:
        flash(
            'Cannot force conversion of bookmarks for selector "{name}" because an existing submission exists.'.format(
                name=sel.student.user.name
            ),
            "error",
        )
        return redirect(redirect_url())

    if not sel.has_bookmarks:
        flash(
            'Cannot force conversion of bookmarks for selector "{name}" because too few bookmarks exist.'.format(
                name=sel.student.user.name
            ),
            "error",
        )
        return redirect(redirect_url())

    stored = store_selection(
        sel,
        converted=converted_status,
        no_submit_IP=no_submit_IP,
        reset=reset,
        force_unavailable=force_unavailable,
    )

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash(
            'Could not force conversion of bookmarks for selector "{name}" because of a database error. '
            "Please contact a system administrator.".format(name=sel.student.user.name),
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
    else:
        if len(stored) > 0:
            report = """
            The following projects were added to the submission for selector "{{ sel.student.user.name }}":
            <ul>
                {% for item in stored %}
                    <li><strong>{{ item.name }}</strong>
                    {% if item.name.generic %}
                        (generic)
                    {% elif item.owner is not none %}
                        owned by <i class="fas fa-user-circle"></i> {{ item.owner.user.name }}
                    {% endif %}
                    </li>
                {% endfor %}
            </ul>
            """
            report_body = render_template_string(report, sel=sel, stored=stored)
            flash(report_body, "info")
        else:
            flash(
                f'No further projects were added to the submission for selector "{sel.student.user.name}". '
                f"This is most likely because no further bookmarked projects are available to this selector.",
                "warning",
            )

    return redirect(redirect_url())


@convenor.route("/custom_CATS_limits/<int:record_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def custom_CATS_limits(record_id):
    # record_id is an EnrollmentRecord
    record = EnrollmentRecord.query.get_or_404(record_id)

    if not validate_is_convenor(record.pclass):
        return redirect(redirect_url())

    form = CustomCATSLimitForm(obj=record)

    if form.validate_on_submit():
        record.CATS_supervision = form.CATS_supervision.data
        record.CATS_marking = form.CATS_marking.data
        record.CATS_moderation = form.CATS_moderation.data
        record.CATS_presentation = form.CATS_presentation.data

        record.last_edit_id = current_user.id
        record.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash(
                "Could not update custom CATS values due to a database error. Please contact a system administrator.",
                "error",
            )
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("convenor.faculty", id=record.pclass.id))

    return render_template_context(
        "convenor/dashboard/custom_CATS_limits.html",
        record=record,
        form=form,
        user=record.owner.user,
    )


@convenor.route("/remove_CATS_limits/<int:record_id>", methods=["GET"])
@roles_accepted("faculty", "admin", "root")
def remove_CATS_limits(record_id):
    # record_id is an EnrollmentRecord
    record = EnrollmentRecord.query.get_or_404(record_id)

    if not validate_is_convenor(record.pclass):
        return redirect(redirect_url())

    record.CATS_supervision = None
    record.CATS_marking = None
    record.CATS_moderation = None
    record.CATS_presentation = None

    record.last_edit_id = current_user.id
    record.last_edit_timestamp = datetime.now()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash(
            "Could not reset custom CATS values due to a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/submission_period_documents/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def submission_period_documents(pid):
    # id is a SubmissionPeriodRecord
    record: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)
    config: ProjectClassConfig = record.config

    # reject is user is not a convenor for the associated project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if this submission period is in the past
    if config.submission_period > record.submission_period:
        flash(
            "It is no longer possible to edit this submission period because it has been closed.",
            "info",
        )
        return redirect(redirect_url())

    # reject if period is retired
    if record.retired:
        flash(
            "It is no longer possible to edit this submission period because it has been retired.",
            "info",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    state = config.submitter_lifecycle
    deletable = (current_user.has_role("root") or current_user.has_role("admin")) or (
            not record.closed
            and (state < config.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY)
    )
    return render_template_context(
        "convenor/documents/period_manager.html",
        record=record,
        url=url,
        text=text,
        state=state,
        config=config,
        deletable=deletable,
    )


@convenor.route("/delete_period_attachment/<int:aid>")
@roles_accepted("faculty", "admin", "root")
def delete_period_attachment(aid):
    # aid is a PeriodAttachment id
    attachment: PeriodAttachment = PeriodAttachment.query.get_or_404(aid)
    asset: SubmittedAsset = attachment.attachment

    if asset is None:
        flash(
            "Could not delete attachment because of a database error. Please contact a system administrator.",
            "info",
        )
        return redirect(redirect_url())

    # check user is convenor the project class this attachment belongs to, or has admin/root privileges
    record: SubmissionPeriodRecord = attachment.parent
    if record is None:
        flash(
            "Can not delete this attachment because it is not attached to a submitter.",
            "info",
        )
        return redirect(redirect_url())

    config: ProjectClassConfig = record.config
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # admin or root users can always delete; otherwise, check that we are not marking
    if not (current_user.has_role("root") or current_user.has_role("admin")):
        if record.closed:
            flash(
                "It is no longer possible to delete documents attached to this submission period, "
                "because it has been closed. A user with admin "
                "privileges can still remove attachments if this is necessary.",
                "info",
            )
            return redirect(redirect_url())

        state = config.submitter_lifecycle
        if state >= config.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY:
            flash(
                "It is no longer possible to delete documents attached to this submission period, "
                "because its marking and feedback phase is now underway. A user with admin privileges "
                "can still remove attachments if this is necessary.",
                "info",
            )
            return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    title = "Delete submission period attachment"
    action_url = url_for(
        "convenor.perform_delete_period_attachment", aid=aid, url=url, text=text
    )

    name = (
        attachment.attachment.target_name
        if attachment.attachment.target_name is not None
        else attachment.attachment.filename
    )
    message = (
        "<p>Please confirm that you wish to remove the attachment <strong>{name}</strong> for "
        "{period}.</p>"
        "<p>This action cannot be undone.</p>".format(
            name=name, period=record.display_name
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


@convenor.route("/perform_delete_period_attachment/<int:aid>")
@roles_accepted("faculty", "admin", "root")
def perform_delete_period_attachment(aid):
    # aid is a PeriodAttachment id
    attachment: PeriodAttachment = PeriodAttachment.query.get_or_404(aid)
    asset: SubmittedAsset = attachment.attachment

    if asset is None:
        flash(
            "Could not delete attachment because of a database error. Please contact a system administrator.",
            "info",
        )
        return redirect(redirect_url())

    # check user is convenor the project class this attachment belongs to, or has admin/root privileges
    record: SubmissionPeriodRecord = attachment.parent
    if record is None:
        flash(
            "Can not delete this attachment because it is not attached to a submitter.",
            "info",
        )
        return redirect(redirect_url())

    config: ProjectClassConfig = record.config
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # admin or root users can always delete; otherwise, check that we are not marking
    if not (current_user.has_role("root") or current_user.has_role("admin")):
        if record.closed:
            flash(
                "It is no longer possible to delete documents attached to this submission period, "
                "because it has been closed. A user with admin "
                "privileges can still remove attachments if this is necessary.",
                "info",
            )
            return redirect(redirect_url())

        state = config.submitter_lifecycle
        if state >= config.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY:
            flash(
                "It is no longer possible to delete documents attached to this submission period, "
                "because its marking and feedback phase is now underway. A user with admin privileges "
                "can still remove attachments if this is necessary.",
                "info",
            )
            return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    # set to expire in 30 days
    asset.expiry = datetime.now() + timedelta(days=30)
    attachment.attachment_id = None

    try:
        db.session.flush()
        db.session.delete(attachment)

        db.session.commit()

    except SQLAlchemyError as e:
        flash(
            "Could not remove attachment from the submission period because of a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(
        url_for(
            "convenor.submission_period_documents", pid=record.id, url=url, text=text
        )
    )


@convenor.route("/upload_period_attachment/<int:pid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def upload_period_attachment(pid):
    # pid is a SubmissionPeriodRecord id
    record: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)

    # check user is convenor for the project's class, or has suitable admin/root privileges
    config: ProjectClassConfig = record.config
    pclass: ProjectClass = config.project_class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    form = UploadPeriodAttachmentForm(request.form)

    if form.validate_on_submit():
        if "attachment" in request.files:
            attachment_file = request.files["attachment"]

            # AssetUploadManager will populate most fields later
            with db.session.no_autoflush:
                asset = SubmittedAsset(
                    timestamp=datetime.now(),
                    uploaded_id=current_user.id,
                    expiry=None,
                    target_name=form.target_name.data,
                    license=form.license.data,
                )

                object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
                with AssetUploadManager(
                        asset,
                        data=attachment_file.stream.read(),
                        storage=object_store,
                        audit_data=f"upload_period_attachment (period id #{pid})",
                        length=attachment_file.content_length,
                        mimetype=attachment_file.content_type,
                        validate_nonce=validate_nonce,
                ) as upload_mgr:
                    pass

            try:
                db.session.add(asset)
                db.session.flush()
            except SQLAlchemyError as e:
                flash(
                    "Could not upload attachment due to a database issue. Please contact an administrator.",
                    "error",
                )
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return redirect(
                    url_for(
                        "convenor.submission_period_documents",
                        pid=pid,
                        url=url,
                        text=text,
                    )
                )

            # generate attachment record
            attachment = PeriodAttachment(
                parent_id=record.id,
                attachment_id=asset.id,
                publish_to_students=form.publish_to_students.data,
                include_marker_emails=form.include_marker_emails.data,
                include_supervisor_emails=form.include_supervisor_emails.data,
                description=form.description.data,
                rank_order=get_count(record.attachments) + 1,
            )

            # uploading user has access
            asset.grant_user(current_user)

            # project convenor has access
            # 'office', 'convenor', 'moderator', 'exam_board' and 'external_examiner' roles all have access
            asset.grant_roles(
                ["office", "convenor", "moderator", "exam_board", "external_examiner"]
            )

            # if available to students, any student can download
            if form.publish_to_students.data:
                asset.grant_role("student")

            if form.include_marker_emails.data or form.include_supervisor_emails.data:
                asset.grant_role("faculty")

            try:
                db.session.add(attachment)
                db.session.commit()
            except SQLAlchemyError as e:
                flash(
                    "Could not upload attachment due to a database issue. Please contact an administrator.",
                    "error",
                )
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

            flash(
                'Attachment "{file}" was successfully uploaded.'.format(
                    file=attachment_file.filename
                ),
                "info",
            )

            return redirect(
                url_for(
                    "convenor.submission_period_documents", pid=pid, url=url, text=text
                )
            )

    else:
        if request.method == "GET":
            form.license.data = current_user.default_license

    return render_template_context(
        "convenor/documents/upload_period_attachment.html",
        record=record,
        form=form,
        url=url,
        text=text,
    )


@convenor.route("/edit_period_attachment/<int:aid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_period_attachment(aid):
    # pid is a PeriodAttachment id
    record: PeriodAttachment = PeriodAttachment.query.get_or_404(aid)

    # check user is convenor for the project's class, or has suitable admin/root privileges
    period: SubmissionPeriodRecord = record.parent
    config: ProjectClassConfig = period.config
    pclass: ProjectClass = config.project_class

    asset = record.attachment
    if asset is None:
        flash(
            "Cannot edit this attachment due to a database error. Please contact a system administrator.",
            "info",
        )
        return redirect(redirect_url())

    # ensure logged-in user has edit privileges
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    form = EditPeriodAttachmentForm(obj=record)

    if form.validate_on_submit():
        record.publish_to_students = form.publish_to_students.data
        record.include_marker_emails = form.include_marker_emails.data
        record.include_supervisor_emails = form.include_supervisor_emails.data
        record.description = form.description.data

        if asset is not None:
            asset.license = form.license.data

            if form.publish_to_students.data:
                asset.grant_role("student")
            else:
                asset.revoke_role("student")

            if form.include_marker_emails.data or form.include_supervisor_emails.data:
                asset.grant_roles(["faculty", "office"])
            # else:
            #     asset.revoke_roles(['faculty', 'office'])

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash(
                "Could not commit edits due to a database issue. Please contact an administrator.",
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)

    else:
        if request.method == "GET":
            form.license.data = asset.license if asset is not None else None

    return render_template_context(
        "convenor/documents/edit_period_attachment.html",
        attachment=record,
        record=period,
        asset=asset,
        form=form,
        url=url,
        text=text,
    )


def _demap_attachment(item_id):
    result = parse.parse("PA-{attach_id}", item_id)

    return int(result["attach_id"])


@convenor.route("/update_period_attachments", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def update_period_attachments():
    data = request.get_json()

    # discard if request is ill-formed
    if "ranking" not in data or "period_id" not in data:
        return jsonify({"status": "ill_formed"})

    ranking = data["ranking"]
    period_id = data["period_id"]

    # attach_id is a SubmissionPeriodRecord
    record: SubmissionPeriodRecord = (
        db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()
    )

    if record is None:
        return jsonify({"status": "data_missing"})

    if not validate_is_convenor(record.config.project_class, message=False):
        return jsonify({"status": "insufficient_privileges"})

    items = map(_demap_attachment, ranking)

    rmap = {}
    index = 1
    for p in items:
        rmap[p] = index
        index += 1

    # update ranking
    for attach in record.attachments:
        attach: PeriodAttachment
        attach.rank_order = rmap[attach.id]

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return jsonify({"status": "database_failure"})

    return jsonify({"status": "success"})
