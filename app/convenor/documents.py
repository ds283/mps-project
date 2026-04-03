#
# Created by David Seery on 24/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from datetime import datetime, timedelta

import parse
from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    render_template_string,
    request,
    url_for,
)
from flask_security import current_user, roles_accepted
from sqlalchemy.exc import SQLAlchemyError

from app.convenor import convenor

from ..database import db
from ..documents.forms import EditPeriodAttachmentForm, UploadPeriodAttachmentForm
from ..models import (
    EnrollmentRecord,
    PeriodAttachment,
    ProjectClass,
    ProjectClassConfig,
    SelectingStudent,
    SubmissionPeriodRecord,
    SubmittedAsset,
)
from ..models.model_mixins import SubmissionRoleTypesMixin
from ..shared.asset_tools import AssetUploadManager
from ..shared.context.global_context import render_template_context
from ..shared.security import validate_nonce
from ..shared.sqlalchemy import get_count
from ..shared.utils import (
    redirect_url,
)
from ..shared.validators import (
    validate_is_convenor,
)
from ..shared.workflow_logging import log_db_commit
from ..student.actions import store_selection
from ..tasks.thumbnails import dispatch_thumbnail_task
from .forms import (
    CustomCATSLimitForm,
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

    log_db_commit(
        "Updated CATS limits for project class config to match project class defaults",
        user=current_user,
        project_classes=config.project_class,
    )

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
        log_db_commit(
            f"Forced conversion of bookmarks to selections for selector {sel.student.user.name}",
            user=current_user,
            student=sel.student,
            project_classes=sel.config.project_class,
        )
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
            log_db_commit(
                f"Updated custom CATS limits for faculty member {record.owner.user.name} in project class {record.pclass.name}",
                user=current_user,
                project_classes=record.pclass,
            )
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
        log_db_commit(
            f"Removed custom CATS limits for faculty member {record.owner.user.name} in project class {record.pclass.name}",
            user=current_user,
            project_classes=record.pclass,
        )
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

        log_db_commit(
            f"Deleted attachment from submission period {record.display_name}",
            user=current_user,
            project_classes=config.project_class,
        )

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

            dispatch_thumbnail_task(asset)

            # generate attachment record
            attachment = PeriodAttachment(
                parent_id=record.id,
                attachment_id=asset.id,
                description=form.description.data,
                rank_order=get_count(record.attachments) + 1,
            )

            try:
                db.session.add(attachment)
                db.session.flush()  # populate attachment.id before set_roles()
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

            selected_roles = form.roles.data or []
            attachment.set_roles(selected_roles)

            # uploader is a convenor or has admin/root privileges, so we don't need to provide user-level access

            # convenors always have access, and office admin roles all have access
            asset.grant_roles(["office", "convenor"])

            # grant asset-level access based on selected roles
            if SubmissionRoleTypesMixin.ROLE_STUDENT in selected_roles:
                asset.grant_role("student")

            _faculty_roles = {
                SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
                SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
                SubmissionRoleTypesMixin.ROLE_MARKER,
                SubmissionRoleTypesMixin.ROLE_MODERATOR,
                SubmissionRoleTypesMixin.ROLE_PRESENTATION_ASSESSOR,
            }
            if _faculty_roles & set(selected_roles):
                asset.grant_role("faculty")

            # NOTE "moderator" role is not really implemented
            # moderators will typically be drawn from enrolled faculty members who all have the "faculty" role
            if SubmissionRoleTypesMixin.ROLE_MODERATOR in selected_roles:
                asset.grant_role("moderator")

            if SubmissionRoleTypesMixin.ROLE_EXAM_BOARD in selected_roles:
                asset.grant_role("exam_board")

            if SubmissionRoleTypesMixin.ROLE_EXTERNAL_EXAMINER in selected_roles:
                asset.grant_role("external_examiner")

            try:
                log_db_commit(
                    f"Uploaded attachment '{attachment_file.filename}' to submission period {record.display_name}",
                    user=current_user,
                    project_classes=pclass,
                )
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
        record.description = form.description.data

        selected_roles = form.roles.data or []
        record.set_roles(selected_roles)

        if asset is not None:
            asset.license = form.license.data

            if SubmissionRoleTypesMixin.ROLE_STUDENT in selected_roles:
                asset.grant_role("student")
            else:
                asset.revoke_role("student")

            _faculty_roles = {
                SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
                SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
                SubmissionRoleTypesMixin.ROLE_MARKER,
                SubmissionRoleTypesMixin.ROLE_MODERATOR,
                SubmissionRoleTypesMixin.ROLE_EXAM_BOARD,
                SubmissionRoleTypesMixin.ROLE_EXTERNAL_EXAMINER,
            }
            if _faculty_roles & set(selected_roles):
                asset.grant_role("faculty")

        try:
            log_db_commit(
                f"Edited attachment details for submission period {period.display_name}",
                user=current_user,
                project_classes=pclass,
            )
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
            form.roles.data = list(record.role_set)

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
        log_db_commit(
            f"Updated attachment rank ordering for submission period #{period_id}",
            user=current_user,
            project_classes=record.config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return jsonify({"status": "database_failure"})

    return jsonify({"status": "success"})
