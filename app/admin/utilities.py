#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import List

from celery import chain
from flask import (
    abort,
    current_app,
    flash,
    redirect,
    request,
    send_file,
    session,
    url_for,
)
from flask_security import (
    current_user,
    login_required,
    login_user,
    roles_accepted,
    roles_required,
)
from sqlalchemy.exc import SQLAlchemyError

import app.ajax as ajax
import app.shared.cloud_object_store.bucket_types as buckets

from ..cache import cache
from ..database import db
from ..models import (
    BackupRecord,
    Building,
    DownloadCentreItem,
    EmailTemplate,
    EmailTemplateLabel,
    FeedbackAsset,
    FeedbackRecipe,
    GeneratedAsset,
    GeneratedAssetDownloadRecord,
    MatchingAttempt,
    PeriodAttachment,
    ProjectClass,
    ProjectClassConfig,
    Room,
    ScheduleAttempt,
    ScheduleSlot,
    SelectingStudent,
    SubmissionAttachment,
    SubmittedAsset,
    SubmittedAssetDownloadRecord,
    TemplateTag,
    TemporaryAsset,
    User,
)
from ..models.submissions import SubmissionRoleTypesMixin
from ..models.assets import ThumbnailAsset
from ..shared.asset_tools import AssetCloudAdapter, AssetUploadManager
from ..shared.backup import (
    create_new_backup_labels,
)
from ..shared.context.global_context import render_template_context
from ..shared.email_templates import clone_email_template
from ..shared.forms.queries import ScheduleSessionQuery
from ..shared.sqlalchemy import get_count
from ..shared.utils import (
    home_dashboard,
    redirect_url,
)
from ..shared.workflow_logging import log_db_commit
from ..task_queue import register_task
from ..tasks.thumbnails import (
    dispatch_force_regenerate_thumbnail_task,
    dispatch_thumbnail_task,
)
from ..tools import ServerSideInMemoryHandler, ServerSideSQLHandler
from ..tools.ServerSideProcessing import FakeQuery
from . import admin
from .forms import (
    AddBuildingForm,
    AddFeedbackRecipeForm,
    AddRoomForm,
    EditBackupForm,
    EditBuildingForm,
    EditEmailTemplateForm,
    EditFeedbackAssetForm,
    EditFeedbackRecipeForm,
    EditRoomForm,
    PublicScheduleFormFactory,
    UploadFeedbackAssetForm,
    UploadMatchForm,
    UploadScheduleForm,
)


@admin.route("/edit_rooms")
@roles_required("root")
def edit_rooms():
    """
    Manage bookable venues for presentation sessions
    :return:
    """
    return render_template_context("admin/presentations/edit_rooms.html", pane="rooms")


@admin.route("/rooms_ajax")
@roles_required("root")
def rooms_ajax():
    """
    AJAX entrypoint for list of available rooms
    :return:
    """

    rooms = db.session.query(Room).all()
    return ajax.admin.rooms_data(rooms)


@admin.route("/add_room", methods=["GET", "POST"])
@roles_required("root")
def add_room():
    # check whether any active buildings exist, and raise an error if not
    if not db.session.query(Building).filter_by(active=True).first():
        flash(
            "No buildings are available. Set up at least one active building before adding a room.",
            "error",
        )
        return redirect(redirect_url())

    form: AddRoomForm = AddRoomForm(request.form)

    if form.validate_on_submit():
        data = Room(
            building_id=form.building.data.id,
            name=form.name.data,
            capacity=form.capacity.data,
            lecture_capture=form.lecture_capture.data,
            maximum_occupancy=form.maximum_occupancy.data,
            active=True,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        db.session.add(data)
        log_db_commit(f"Added new venue room '{data.name}'", user=current_user)

        return redirect(url_for("admin.edit_rooms"))

    return render_template_context(
        "admin/presentations/edit_room.html", form=form, title="Add new venue"
    )


@admin.route("/edit_room/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_room(id):
    # id is a Room
    data: Room = Room.query.get_or_404(id)

    form: EditRoomForm = EditRoomForm(obj=data)
    form.room = data

    if form.validate_on_submit():
        data.name = form.name.data
        data.building = form.building.data
        data.capacity = form.capacity.data
        data.lecture_capture = form.lecture_capture.data
        data.maximum_occupancy = form.maximum_occupancy.data

        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        log_db_commit(f"Edited venue room '{data.name}'", user=current_user)

        return redirect(url_for("admin.edit_rooms"))

    return render_template_context(
        "admin/presentations/edit_room.html", form=form, room=data, title="Edit venue"
    )


@admin.route("/activate_room/<int:id>")
@roles_required("root")
def activate_room(id):
    # id is a Room
    data = Room.query.get_or_404(id)

    data.enable()
    log_db_commit(f"Activated venue room '{data.name}'", user=current_user)

    return redirect(redirect_url())


@admin.route("/deactivate_room/<int:id>")
@roles_required("root")
def deactivate_room(id):
    # id is a Room
    data = Room.query.get_or_404(id)

    data.disable()
    log_db_commit(f"Deactivated venue room '{data.name}'", user=current_user)

    return redirect(redirect_url())


@admin.route("/edit_buildings")
@roles_required("root")
def edit_buildings():
    """
    Manage list of buildings to which bookable venues can belong.
    Essentially used to identify rooms in the same building with a coloured tag.
    :return:
    """
    return render_template_context(
        "admin/presentations/edit_buildings.html", pane="buildings"
    )


@admin.route("/buildings_ajax")
@roles_required("root")
def buildings_ajax():
    """
    AJAX entrypoint for list of available buildings
    :return:
    """

    buildings = db.session.query(Building).all()
    return ajax.admin.buildings_data(buildings)


@admin.route("/add_building", methods=["GET", "POST"])
@roles_required("root")
def add_building():
    form = AddBuildingForm(request.form)

    if form.validate_on_submit():
        data = Building(
            name=form.name.data,
            colour=form.colour.data,
            active=True,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        db.session.add(data)
        log_db_commit(f"Added new building '{data.name}'", user=current_user)

        return redirect(url_for("admin.edit_buildings"))

    return render_template_context(
        "admin/presentations/edit_building.html", form=form, title="Add new building"
    )


@admin.route("/edit_building/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_building(id):
    # id is a Building
    data = Building.query.get_or_404(id)

    form = EditBuildingForm(obj=data)
    form.building = data

    if form.validate_on_submit():
        data.name = form.name.data
        data.colour = form.colour.data

        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        log_db_commit(f"Edited building '{data.name}'", user=current_user)

        return redirect(url_for("admin.edit_buildings"))

    return render_template_context(
        "admin/presentations/edit_building.html",
        form=form,
        building=data,
        title="Edit building",
    )


@admin.route("/activate_building/<int:id>")
@roles_required("root")
def activate_building(id):
    # id is a Building
    data = Building.query.get_or_404(id)

    data.enable()
    log_db_commit(f"Activated building '{data.name}'", user=current_user)

    return redirect(redirect_url())


@admin.route("/deactivate_building/<int:id>")
@roles_required("root")
def deactivate_building(id):
    # id is a Building
    data = Building.query.get_or_404(id)

    data.disable()
    log_db_commit(f"Deactivated building '{data.name}'", user=current_user)

    return redirect(redirect_url())


@admin.route("/launch_test_task")
@roles_required("root")
def launch_test_task():
    task_id = register_task(
        "Test task", owner=current_user, description="Long-running test task"
    )

    celery = current_app.extensions["celery"]
    test_task = celery.tasks["app.tasks.test.test_task"]

    test_task.apply_async(task_id=task_id)

    return "success"


@admin.route("/login_as/<int:id>")
@roles_required("root")
def login_as(id):
    user = User.query.get_or_404(id)

    # store previous login identifier
    # this is OK *provided* we only ever use server-side sessions for security, so that the session
    # variables can not be edited, inspected or faked by the user
    session["previous_login"] = current_user.id

    current_app.logger.info(
        "{real} used superuser powers to log in as alternative user {fake}".format(
            real=current_user.name, fake=user.name
        )
    )

    login_user(user, remember=False)
    # don't commit changes to database to avoid confusing this with a real login

    return home_dashboard()


@admin.route("/download_generated_asset/<int:asset_id>")
@login_required
def download_generated_asset(asset_id):
    # asset_is is a GeneratedAsset
    asset = GeneratedAsset.query.get_or_404(asset_id)

    if not asset.has_access(current_user.id):
        flash(
            "You do not have permissions to download this asset. If you think this is a mistake, please contact a system administrator.",
            "info",
        )
        return redirect(redirect_url())

    filename = request.args.get("filename", None)

    bucket_map = bucket_map = current_app.config.get("OBJECT_STORAGE_BUCKETS")

    if asset.bucket not in bucket_map:
        flash(
            f"This object is stored in a bucket (type={asset.bucket}) which is not part of the configured storage. "
            f"Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    # log this download
    download_item_id = request.args.get("download_item_id", None)
    if download_item_id is not None:
        download_item: DownloadCentreItem = DownloadCentreItem.query.get_or_404(
            download_item_id
        )

        download_item.last_downloaded_at = datetime.now()
        download_item.number_downloads += 1

    record = GeneratedAssetDownloadRecord(
        asset_id=asset.id, downloader_id=current_user.id, timestamp=datetime.now()
    )

    try:
        db.session.add(record)
        log_db_commit(
            f"Logged download of generated asset #{asset_id}", user=current_user
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not serve download request for asset_id={number} because of a database error. "
            "Please contact a system administrator".format(number=asset_id),
            "error",
        )
        return redirect(redirect_url())

    object_store = bucket_map[asset.bucket]
    storage = AssetCloudAdapter(
        asset,
        object_store,
        audit_data=f"download_generated_asset (asset id #{asset_id})",
    )
    return_data = BytesIO()
    with storage.download_to_scratch() as scratch_path:
        file_path = scratch_path.path

        with open(file_path, "rb") as f:
            return_data.write(f.read())
        return_data.seek(0)

    return send_file(
        return_data,
        mimetype=asset.mimetype,
        download_name=filename if filename else asset.target_name,
        as_attachment=True,
    )


@admin.route("/download_submitted_asset/<int:asset_id>")
@login_required
def download_submitted_asset(asset_id):
    # asset_is is a SubmittedAsset
    asset: SubmittedAsset = SubmittedAsset.query.get_or_404(asset_id)

    sub_attachment: SubmissionAttachment = asset.submission_attachment
    period_attachment: PeriodAttachment = asset.period_attachment

    attachment = (
        sub_attachment
        if sub_attachment is not None
        else period_attachment
        if period_attachment is not None
        else None
    )

    # attachment may be 'None' if this is an asset that does not have a specific attachment record, e.g., the
    # unprocessed report is usually of this type

    # if an attachment record is available, check its 'publish_to_students' flag
    if attachment is not None:
        if current_user.has_role("student") and not attachment.has_role_access(SubmissionRoleTypesMixin.ROLE_STUDENT):
            # give no indication that this asset actually exists
            abort(404)

    if not asset.has_access(current_user.id):
        flash(
            "You do not have permissions to download this asset. If you think this is a mistake, please contact a system administrator.",
            "info",
        )
        return redirect(redirect_url())

    filename = request.args.get("filename", None)

    bucket_map = current_app.config.get("OBJECT_STORAGE_BUCKETS")

    if asset.bucket not in bucket_map:
        flash(
            f"This object is stored in a bucket (type={asset.bucket}) which is not part of the configured storage. "
            f"Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    # log this download
    record = SubmittedAssetDownloadRecord(
        asset_id=asset.id, downloader_id=current_user.id, timestamp=datetime.now()
    )

    try:
        db.session.add(record)
        log_db_commit(
            f"Logged download of submitted asset #{asset_id}", user=current_user
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not serve download request for asset_id={number} because of a database error. "
            "Please contact a system administrator".format(number=asset_id),
            "error",
        )
        return redirect(redirect_url())

    object_store = bucket_map[asset.bucket]
    storage = AssetCloudAdapter(
        asset,
        current_app.config["OBJECT_STORAGE_ASSETS"],
        audit_data=f"download_submitted_asset (asset id #{asset_id})",
    )
    return_data = BytesIO()
    with storage.download_to_scratch() as scratch_path:
        file_path = scratch_path.path

        with open(file_path, "rb") as f:
            return_data.write(f.read())
        return_data.seek(0)

    return send_file(
        return_data,
        mimetype=asset.mimetype,
        download_name=filename if filename else asset.target_name,
        as_attachment=True,
    )


@admin.route("/download_backup/<int:backup_id>")
@roles_required("root")
def download_backup(backup_id):
    # backup_id is a BackupRecord instance
    backup: BackupRecord = BackupRecord.query.get_or_404(backup_id)

    filename = request.args.get("filename", None)

    storage = AssetCloudAdapter(
        backup,
        current_app.config["OBJECT_STORAGE_BACKUP"],
        audit_data=f"download_backup (backup id #{backup_id})",
        size_attr="archive_size",
    )
    return_data = BytesIO()
    with storage.download_to_scratch() as scratch_path:
        file_path = scratch_path.path

        with open(file_path, "rb") as f:
            return_data.write(f.read())
        return_data.seek(0)

    fname = Path(filename if filename else backup.unique_name)
    while fname.suffix:
        fname = fname.with_suffix("")
    fname = fname.with_suffix(".tar.gz")
    return send_file(
        return_data,
        mimetype="application/gzip",
        download_name=str(fname),
        as_attachment=True,
    )


@admin.route("/lock_backup/<int:backup_id>")
@roles_required("root")
def lock_backup(backup_id):
    # backup_id is a BackupRecord instance
    backup: BackupRecord = BackupRecord.query.get_or_404(backup_id)

    try:
        backup.locked = True
        log_db_commit(f"Locked backup record #{backup_id}", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not lock this backup because of a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@admin.route("/unlock_backup/<int:backup_id>")
@roles_required("root")
def unlock_backup(backup_id):
    # backup_id is a BackupRecord instance
    backup: BackupRecord = BackupRecord.query.get_or_404(backup_id)

    try:
        backup.locked = False
        log_db_commit(f"Unlocked backup record #{backup_id}", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not lock this backup because of a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@admin.route("/edit_backup/<int:backup_id>", methods=["GET", "POST"])
@roles_required("root")
def edit_backup(backup_id):
    # backup_id is a BackupRecord instance
    backup: BackupRecord = BackupRecord.query.get_or_404(backup_id)

    form = EditBackupForm(obj=backup)

    if form.validate_on_submit():
        label_list = create_new_backup_labels(form)

        backup.labels = label_list
        backup.locked = form.locked.data

        if not backup.locked:
            backup.unlock_date = None
        else:
            backup.unlock_date = form.unlock_date.data

        try:
            log_db_commit(
                f"Saved labels and settings for backup record #{backup_id}",
                user=current_user,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemy exception", exc_info=e)
            flash(
                "Could not save labels for this backup record due to a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.manage_backups"))

    else:
        if request.method == "GET" and not form.locked.data:
            default_unlock_date = date.today() + timedelta(weeks=24)

            form.unlock_date.data = default_unlock_date

    return render_template_context("admin/edit_backup.html", backup=backup, form=form)


@admin.route("/upload_schedule/<int:schedule_id>", methods=["GET", "POST"])
@roles_required("root")
def upload_schedule(schedule_id):
    # schedule_id is a ScheduleAttempt
    record = ScheduleAttempt.query.get_or_404(schedule_id)

    form = UploadScheduleForm(request.form)

    if form.validate_on_submit():
        if "solution" in request.files:
            sol_file = request.files["solution"]

            # generate new filename for upload
            incoming_filename = Path(sol_file.filename)
            extension = incoming_filename.suffix.lower()

            if extension in (".sol", ".lp", ".mps"):
                if (
                    form.solver.data == ScheduleAttempt.SOLVER_CBC_PACKAGED
                    or form.solver.data == ScheduleAttempt.SOLVER_CBC_CMD
                ) and extension not in (".lp",):
                    flash(
                        "Solution files for the CBC optimizer must be in .LP format",
                        "error",
                    )

                else:
                    now = datetime.now()
                    asset = TemporaryAsset(
                        timestamp=now, expiry=now + timedelta(days=1)
                    )

                    object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
                    with AssetUploadManager(
                        asset,
                        data=sol_file.stream.read(),
                        storage=object_store,
                        audit_data=f"upload_schedule (schedule id #{schedule_id})",
                        length=sol_file.content_length,
                    ) as upload_mgr:
                        pass

                    asset.grant_user(current_user)

                    uuid = register_task(
                        'Process offline solution for "{name}"'.format(
                            name=record.name
                        ),
                        owner=current_user,
                        description="Import a solution file that has been produced offline and convert to a schedule",
                    )

                    # update solver information from form
                    record.solver = form.solver.data
                    record.celery_finished = False
                    record.celery_id = uuid

                    try:
                        db.session.add(asset)
                        log_db_commit(
                            f"Uploaded offline schedule solution for schedule #{schedule_id}",
                            user=current_user,
                        )
                    except SQLAlchemyError as e:
                        db.session.rollback()
                        flash(
                            "Could not upload offline solution due to a database issue. Please contact an administrator.",
                            "error",
                        )
                        current_app.logger.exception(
                            "SQLAlchemyError exception", exc_info=e
                        )
                        return redirect(
                            url_for("admin.assessment_schedules", id=record.owner_id)
                        )

                    celery = current_app.extensions["celery"]
                    schedule_task = celery.tasks[
                        "app.tasks.scheduling.process_offline_solution"
                    ]

                    schedule_task.apply_async(
                        args=(record.id, asset.id, current_user.id), task_id=uuid
                    )

                    return redirect(
                        url_for("admin.assessment_schedules", id=record.owner_id)
                    )

            else:
                flash(
                    "Optimizer solution files should have extension .sol or .mps.",
                    "error",
                )

    else:
        if request.method == "GET":
            form.solver.data = record.solver

    return render_template_context(
        "admin/presentations/scheduling/upload.html", schedule=record, form=form
    )


@admin.route("/upload_match/<int:match_id>", methods=["GET", "POST"])
@roles_required("root")
def upload_match(match_id):
    # match_id is a MatchingAttempt
    record = MatchingAttempt.query.get_or_404(match_id)

    form = UploadMatchForm(request.form)

    if form.validate_on_submit():
        if "solution" in request.files:
            sol_file = request.files["solution"]

            # generate new filename for upload
            incoming_filename = Path(sol_file.filename)
            extension = incoming_filename.suffix.lower()

            if extension in (".sol", ".lp", ".mps"):
                if (
                    form.solver.data == ScheduleAttempt.SOLVER_CBC_PACKAGED
                    or form.solver.data == ScheduleAttempt.SOLVER_CBC_CMD
                ) and extension not in (".lp",):
                    flash(
                        "Solution files for the CBC optimizer must be in .LP format",
                        "error",
                    )

                else:
                    now = datetime.now()
                    asset = TemporaryAsset(
                        timestamp=now, expiry=now + timedelta(days=1)
                    )

                    object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
                    with AssetUploadManager(
                        asset,
                        data=sol_file.stream.read(),
                        storage=object_store,
                        audit_data=f"upload_match (match id #{match_id})",
                        length=sol_file.content_length,
                    ) as upload_mgr:
                        pass

                    asset.grant_user(current_user)

                    uuid = register_task(
                        'Process offline solution for "{name}"'.format(
                            name=record.name
                        ),
                        owner=current_user,
                        description="Import a solution file that has been produced offline and convert to a project match",
                    )

                    # update solver information from form
                    record.solver = form.solver.data
                    record.celery_finished = False
                    record.celery_id = uuid

                    try:
                        db.session.add(asset)
                        log_db_commit(
                            f"Uploaded offline match solution for match #{match_id}",
                            user=current_user,
                        )
                    except SQLAlchemyError as e:
                        db.session.rollback()
                        flash(
                            "Could not upload offline solution due to a database issue. Please contact an administrator.",
                            "error",
                        )
                        current_app.logger.exception(
                            "SQLAlchemyError exception", exc_info=e
                        )
                        return redirect(url_for("admin.manage_matching"))

                    celery = current_app.extensions["celery"]
                    schedule_task = celery.tasks[
                        "app.tasks.matching.process_offline_solution"
                    ]

                    schedule_task.apply_async(
                        args=(record.id, asset.id, current_user.id), task_id=uuid
                    )

                    return redirect(url_for("admin.manage_matching"))

            else:
                flash(
                    "Optimizer solution files should have extension .sol or .mps.",
                    "error",
                )

    else:
        if request.method == "GET":
            form.solver.data = record.solver

    return render_template_context(
        "admin/matching/upload.html", match=record, form=form
    )


@admin.route("/view_schedule/<string:tag>", methods=["GET", "POST"])
def view_schedule(tag):
    schedule: ScheduleAttempt = (
        db.session.query(ScheduleAttempt).filter_by(tag=tag).first()
    )
    if schedule is None:
        abort(404)

    # TODO: need UI for setting redirect_tag
    if schedule.redirect_tag is not None:
        return redirect(url_for("admin.view_schedule", tag=schedule.redirect_tag))

    # deployed schedules are automatically unpublished, so we should allow public viewing if either flag is set
    if not (schedule.published or schedule.deployed):
        abort(404)

    PublicScheduleForm = PublicScheduleFormFactory(schedule)
    form = PublicScheduleForm(request.form)

    if not form.validate_on_submit() and request.method == "GET":
        form.selector.data = ScheduleSessionQuery(schedule.id).first()

    event = schedule.owner

    selected_session = form.selector.data

    if selected_session is not None:
        slots = (
            db.session.query(ScheduleSlot)
            .filter(
                ScheduleSlot.owner_id == schedule.id,
                ScheduleSlot.session_id == selected_session.id,
            )
            .join(Room, ScheduleSlot.room_id == Room.id)
            .join(Building, Room.building_id == Building.id)
            .order_by(Building.name.asc(), Room.name.asc())
            .all()
        )

    else:
        slots = []

    return render_template_context(
        "admin/presentations/public/schedule.html",
        form=form,
        event=event,
        schedule=schedule,
        slots=slots,
    )


@admin.route("/reset_tasks")
@roles_accepted("admin", "root")
def reset_tasks():
    celery = current_app.extensions["celery"]
    reset = celery.tasks["app.tasks.system.reset_tasks"]
    reset.si(current_user.id).apply_async()

    return redirect(redirect_url())


@admin.route("/clear_redis_cache")
@roles_accepted("root")
def clear_redis_cache():
    cache.clear()

    flash("The website cache has been successfully cleared.", "success")

    return redirect(redirect_url())


@admin.route("/move_selector/<int:sid>")
@roles_accepted("admin", "root")
def move_selector(sid):
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    url = request.args.get("url")
    text = request.args.get("text")
    if url is None:
        url = redirect_url()

    available = set()

    pclasses: List[ProjectClass] = (
        db.session.query(ProjectClass)
        .filter(ProjectClass.active, ProjectClass.id != sel.config.pclass_id)
        .all()
    )

    for pcl in pclasses:
        config: ProjectClassConfig = pcl.most_recent_config

        # reject if not gone live, since then we cannot match up project choices
        if not config.live:
            continue

        # reject if this student is already a selector for this project class
        if (
            get_count(
                config.selecting_students.filter(
                    SelectingStudent.student_id == sel.student_id
                )
            )
            > 0
        ):
            continue

        available.add(config)

    if len(available) == 0:
        flash(
            'Selector <i class="fas fa-user-circle"></i> {name} cannot be moved at this time because there are no '
            "live project classes available as destinations.".format(
                name=sel.student.user.name
            ),
            "info",
        )
        return redirect(url)

    return render_template_context(
        "admin/move_selector.html",
        sel=sel,
        student=sel.student,
        available=available,
        url=url,
        text=text,
    )


@admin.route("/do_move_selector/<int:sid>/<int:dest_id>")
@roles_accepted("admin", "root")
def do_move_selector(sid, dest_id):
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)
    dest_config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(dest_id)

    url = request.args.get("url")
    if url is None:
        url = redirect_url()

    # reject if source and destination are the same
    if sel.config_id == dest_config.id:
        flash(
            'Cannot move selector <i class="fas fa-user-circle"></i> {name} to project class "{pcl}" because it '
            "is already attached.".format(
                name=sel.student.user.name, pcl=dest_config.name
            ),
            "error",
        )
        return redirect(url)

    # reject is destination has not gone live
    if not dest_config.live:
        flash(
            'Cannot move selector <i class="fas fa-user-circle"></i> {name} to project class "{pcl}" because it '
            "is not yet live in this academic "
            "cycle.".format(name=sel.student.user.name, pcl=dest_config.name),
            "error",
        )
        return redirect(url)

    # reject is this student is already selecting for destination
    if (
        get_count(
            dest_config.selecting_students.filter(
                SelectingStudent.student_id == sel.student_id
            )
        )
        > 0
    ):
        flash(
            'Cannot move selector <i class="fas fa-user-circle"></i> {name} to project class "{pcl}" '
            "because this student is already selecting for "
            "it.".format(name=sel.student.user.name, pcl=dest_config.name),
            "error",
        )
        return redirect(url)

    # hand off job to asynchronous task backend since potentially long-running on a big database
    celery = current_app.extensions["celery"]
    move_selector = celery.tasks["app.tasks.selecting.move_selector"]

    tk_name = "Move selector"
    tk_description = 'Move selector {name} to project class "{pcl}"'.format(
        name=sel.student.user.name, pcl=dest_config.name
    )
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(
        init.si(task_id, tk_name),
        move_selector.si(sid, dest_id, current_user.id),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(url)


def create_new_template_tags(form):
    matched, unmatched = form.tags.data

    if len(unmatched) > 0:
        now = datetime.now()
        for tag in unmatched:
            new_tag = TemplateTag(
                name=tag,
                colour=None,
                creator_id=current_user.id,
                creation_timestamp=now,
            )
            try:
                db.session.add(new_tag)
                matched.append(new_tag)
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                flash(
                    f'Could not add newly defined tag "{tag}" due to a database error. Please contact a system administrator.',
                    "error",
                )

    return matched


@admin.route("/inspect_assets")
@roles_required("admin", "root")
def inspect_assets():
    """
    View to inspect all GeneratedAsset, TemporaryAsset, and SubmittedAsset records
    :return:
    """
    has_thumbnail_errors = (
        db.session.query(GeneratedAsset).filter_by(thumbnail_error=True).count()
        + db.session.query(SubmittedAsset).filter_by(thumbnail_error=True).count()
    ) > 0
    return render_template_context(
        "admin/inspect_assets.html", has_thumbnail_errors=has_thumbnail_errors
    )


@admin.route("/assets_ajax", methods=["POST"])
@roles_required("admin", "root")
def assets_ajax():
    """
    AJAX data point for asset inspection view.
    Combines GeneratedAsset, TemporaryAsset, and SubmittedAsset records into a single
    in-memory list and paginates using ServerSideInMemoryHandler.
    :return:
    """
    # Build a combined list of (asset, type_label) tuples from all three asset tables.
    # We use three separate queries and tag each row with its type string so that the
    # row formatter can distinguish them.
    generated = [(a, "GeneratedAsset") for a in db.session.query(GeneratedAsset).all()]
    temporary = [(a, "TemporaryAsset") for a in db.session.query(TemporaryAsset).all()]
    submitted = [(a, "SubmittedAsset") for a in db.session.query(SubmittedAsset).all()]

    combined = generated + temporary + submitted

    fake_query = FakeQuery(combined)

    # Column definitions for in-memory search and sort.
    # Each row is a (asset, asset_type_str) tuple, so accessors receive that tuple.
    def _target_name(row):
        asset, _ = row
        return getattr(asset, "target_name", None) or ""

    def _file_size(row):
        asset, _ = row
        return asset.filesize

    def _mimetype(row):
        asset, _ = row
        return getattr(asset, "mimetype", None) or ""

    def _comment(row):
        asset, _ = row
        return getattr(asset, "comment", None) or ""

    def _expiry_order(row):
        asset, _ = row
        return asset.expiry

    def _timestamp_order(row):
        asset, _ = row
        return asset.timestamp

    target_name = {"search": _target_name, "order": _target_name}
    mimetype = {"search": _mimetype, "order": _mimetype}
    filesize = {"order": _file_size}
    comment = {"search": _comment, "order": _comment}
    expiry = {"order": _expiry_order}
    timestamp = {"order": _timestamp_order}

    columns = {
        "target_name": target_name,
        "timestamp": timestamp,
        "mimetype": mimetype,
        "filesize": filesize,
        "comment": comment,
        "expiry": expiry,
    }

    with ServerSideInMemoryHandler(request, fake_query, columns) as handler:
        return handler.build_payload(ajax.admin.assets_data)


@admin.route("/asset_remove_expiry/<string:asset_type>/<int:asset_id>")
@roles_required("admin", "root")
def asset_remove_expiry(asset_type, asset_id):
    """
    Remove the expiry date from an asset
    :param asset_type: 'generated', 'temporary', or 'submitted'
    :param asset_id: primary key of the asset
    :return:
    """
    if asset_type == "generated":
        asset = GeneratedAsset.query.get_or_404(asset_id)
    elif asset_type == "temporary":
        asset = TemporaryAsset.query.get_or_404(asset_id)
    elif asset_type == "submitted":
        asset = SubmittedAsset.query.get_or_404(asset_id)
    else:
        flash("Unknown asset type '{t}'.".format(t=asset_type), "error")
        return redirect(redirect_url())

    asset.expiry = None

    try:
        log_db_commit(
            f"Removed expiry date from {asset_type} asset #{asset_id}",
            user=current_user,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not remove expiry date because of a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(redirect_url())


@admin.route("/asset_add_expiry/<string:asset_type>/<int:asset_id>")
@roles_required("admin", "root")
def asset_add_expiry(asset_type, asset_id):
    """
    Add an expiry date to an asset
    :param asset_type: 'generated', 'temporary', or 'submitted'
    :param asset_id: primary key of the asset
    :return:
    """
    if asset_type == "generated":
        asset = GeneratedAsset.query.get_or_404(asset_id)
    elif asset_type == "temporary":
        asset = TemporaryAsset.query.get_or_404(asset_id)
    elif asset_type == "submitted":
        asset = SubmittedAsset.query.get_or_404(asset_id)
    else:
        flash("Unknown asset type '{t}'.".format(t=asset_type), "error")
        return redirect(redirect_url())

    if asset.expiry is not None:
        return redirect(redirect_url())

    asset.expiry = datetime.now() + timedelta(days=7)

    try:
        log_db_commit(
            f"Added expiry date to {asset_type} asset #{asset_id}", user=current_user
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not add expiry date because of a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(redirect_url())


_THUMBNAIL_ASSET_TYPES = {
    "GeneratedAsset": GeneratedAsset,
    "SubmittedAsset": SubmittedAsset,
}


@admin.route("/asset_regenerate_thumbnail/<string:asset_type>/<int:asset_id>")
@roles_required("admin", "root")
def asset_regenerate_thumbnail(asset_type, asset_id):
    """
    Dispatch a Celery task to force-regenerate the thumbnail for a GeneratedAsset or SubmittedAsset.
    Clears any existing error state, deletes old thumbnail records/files, and re-generates.
    """
    if asset_type not in _THUMBNAIL_ASSET_TYPES:
        flash(f"Unknown asset type '{asset_type}'.", "error")
        return redirect(redirect_url())

    model_class = _THUMBNAIL_ASSET_TYPES[asset_type]
    asset = model_class.query.get_or_404(asset_id)

    dispatch_force_regenerate_thumbnail_task(asset)
    flash("Thumbnail regeneration has been queued.", "success")
    return redirect(redirect_url())


@admin.route("/asset_clear_thumbnail_error/<string:asset_type>/<int:asset_id>")
@roles_required("admin", "root")
def asset_clear_thumbnail_error(asset_type, asset_id):
    """
    Clear the thumbnail error flag and message for a GeneratedAsset or SubmittedAsset.
    """
    if asset_type not in _THUMBNAIL_ASSET_TYPES:
        flash(f"Unknown asset type '{asset_type}'.", "error")
        return redirect(redirect_url())

    model_class = _THUMBNAIL_ASSET_TYPES[asset_type]
    asset = model_class.query.get_or_404(asset_id)

    asset.thumbnail_error = False
    asset.thumbnail_error_message = None

    try:
        log_db_commit(
            f"Cleared thumbnail error for {asset_type} id #{asset_id}",
            user=current_user,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not clear thumbnail error because of a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(redirect_url())


@admin.route("/generate_all_thumbnails")
@roles_required("admin", "root")
def generate_all_thumbnails():
    """
    Clear thumbnail error state for all GeneratedAsset and SubmittedAsset records,
    then dispatch the thumbnail_maintenance Celery task to regenerate any missing thumbnails.
    """
    try:
        db.session.query(GeneratedAsset).update(
            {"thumbnail_error": False, "thumbnail_error_message": None}
        )
        db.session.query(SubmittedAsset).update(
            {"thumbnail_error": False, "thumbnail_error_message": None}
        )
        log_db_commit(
            "Cleared all thumbnail errors prior to maintenance run", user=current_user
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not clear thumbnail errors because of a database error. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    maintenance_task = celery.tasks["app.tasks.maintenance.thumbnail_maintenance"]
    maintenance_task.apply_async()

    flash(
        "Thumbnail maintenance task has been queued. Missing thumbnails will be regenerated shortly.",
        "success",
    )
    return redirect(redirect_url())


@admin.route("/upload_feedback_asset", methods=["GET", "POST"])
@roles_accepted("admin", "root")
def upload_feedback_asset():
    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    form = UploadFeedbackAssetForm(request.form)

    if form.validate_on_submit():
        if "asset" in request.files:
            asset_file = request.files["asset"]

            # AssetUploadManager will populate most fields later
            asset = SubmittedAsset(
                timestamp=datetime.now(),
                uploaded_id=current_user.id,
                expiry=None,
                target_name=form.label.data,
                license=form.license.data,
            )
            db.session.add(asset)

            object_store = current_app.config.get("OBJECT_STORAGE_PROJECT")
            with AssetUploadManager(
                asset,
                data=asset_file.stream.read(),
                storage=object_store,
                audit_data=f"upload_feedback_asset",
                length=asset_file.content_length,
                mimetype=asset_file.content_type,
            ) as upload_mgr:
                pass

            try:
                db.session.flush()
            except SQLAlchemyError as e:
                db.session.rollback()
                flash(
                    "Could not upload feedback asset due to a database issue. Please contact an administrator.",
                    "error",
                )
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return redirect(url)

            dispatch_thumbnail_task(asset)

            tag_list = create_new_template_tags(form)

            feedback_asset = FeedbackAsset(
                project_classes=form.project_classes.data,
                asset_id=asset.id,
                label=form.label.data,
                description=form.description.data,
                is_template=form.is_template.data,
                tags=tag_list,
                creator_id=current_user.id,
                creation_timestamp=datetime.now(),
            )

            try:
                db.session.add(feedback_asset)
                log_db_commit(
                    f"Uploaded feedback asset '{feedback_asset.label}'",
                    user=current_user,
                )
            except SQLAlchemyError as e:
                db.session.rollback()
                flash(
                    "Feedback asset was uploaded, but there was a database issue. Please contact an administrator.",
                    "error",
                )
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

            return redirect(url)

        else:
            flash("No upload was supplied", "error")

    return render_template_context(
        "admin/feedback/upload_feedback_asset.html", form=form, url=url
    )


@admin.route("/edit_feedback_asset/<int:asset_id>", methods=["GET", "POST"])
@roles_accepted("admin", "root")
def edit_feedback_asset(asset_id):
    # asset id identifies a FeedbackAsset
    asset: FeedbackAsset = FeedbackAsset.query.get_or_404(asset_id)
    asset_record: SubmittedAsset = asset.asset

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    form = EditFeedbackAssetForm(obj=asset)
    form.asset = asset

    if form.validate_on_submit():
        tag_list = create_new_template_tags(form)

        asset.label = form.label.data
        asset.description = form.description.data
        asset.project_classes = form.project_classes.data
        asset.is_template = form.is_template.data
        asset.tags = tag_list

        asset_record.license = form.license.data

        asset.last_edit_id = current_user.id
        asset.last_edit_timestamp = datetime.now()

        try:
            log_db_commit(f"Edited feedback asset '{asset.label}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(
                "Could not save changes to this asset due to a database error. Please contact a system administrator.",
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)
    elif request.method == "GET":
        form.license.data = asset_record.license

    return render_template_context(
        "admin/feedback/edit_feedback_asset.html", form=form, url=url, asset=asset
    )


@admin.route("/add_feedback_recipe", methods=["GET", "POST"])
@roles_accepted("admin", "root")
def add_feedback_recipe():
    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    form = AddFeedbackRecipeForm(request.form)

    if form.validate_on_submit():
        recipe = FeedbackRecipe(
            label=form.label.data,
            project_classes=form.project_classes.data,
            template=form.template.data,
            asset_list=form.asset_list.data,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            db.session.add(recipe)
            log_db_commit(f"Added feedback recipe '{recipe.label}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(
                "Could not add feedback recipe due to a database issue. Please contact an administrator.",
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)

    return render_template_context(
        "admin/feedback/add_feedback_recipe.html", form=form, url=url
    )


@admin.route("/edit_feedback_recipe/<int:recipe_id>", methods=["GET", "POST"])
@roles_accepted("admin", "root")
def edit_feedback_recipe(recipe_id):
    recipe: FeedbackRecipe = FeedbackRecipe.query.get_or_404(recipe_id)

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    form = EditFeedbackRecipeForm(obj=recipe)
    form.recipe = recipe

    if form.validate_on_submit():
        recipe.label = form.label.data
        recipe.project_classes = form.project_classes.data
        recipe.template = form.template.data
        recipe.asset_list = form.asset_list.data

        recipe.last_edit_id = current_user.id
        recipe.last_edit_timestamp = datetime.now()

        try:
            log_db_commit(f"Edited feedback recipe '{recipe.label}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(
                "Could not save changes to this recipe due to a database issue. Please contact an administrator.",
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)

    return render_template_context(
        "admin/feedback/edit_feedback_recipe.html", form=form, url=url, recipe=recipe
    )


# ======================================================================================================================
# EmailTemplate views
# ======================================================================================================================


@admin.route("/global_email_templates")
@roles_required("root")
def global_email_templates():
    """
    List all EmailTemplate instances
    :return:
    """
    AJAX_endpoint = url_for("admin.global_email_templates_ajax")

    return render_template_context(
        "admin/email_templates/list.html",
        AJAX_endpoint=AJAX_endpoint,
        title="All email templates",
        card_title="All email templates",
        inspector_type="global",
    )


@admin.route("/global_email_templates_ajax", methods=["POST"])
@roles_required("root")
def global_email_templates_ajax():
    """
    AJAX data point for email templates list
    :return:
    """
    base_query = db.session.query(EmailTemplate)

    type_col = {"order": EmailTemplate.type}
    subject = {
        "search": EmailTemplate.subject,
        "order": EmailTemplate.subject,
        "search_collation": "utf8_general_ci",
    }
    version = {"order": EmailTemplate.version}
    status = {"order": EmailTemplate.active}
    comment = {
        "search": EmailTemplate.comment,
        "order": EmailTemplate.comment,
        "search_collation": "utf8_general_ci",
    }

    columns = {
        "type": type_col,
        "subject": subject,
        "version": version,
        "status": status,
        "comment": comment,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.admin.email_templates_data)


def create_new_email_template_labels(form):
    matched, unmatched = form.labels.data

    if len(unmatched) > 0:
        now = datetime.now()
        for label in unmatched:
            new_label = EmailTemplateLabel(
                name=label,
                colour=None,
                creator_id=current_user.id,
                creation_timestamp=now,
            )
            try:
                db.session.add(new_label)
                matched.append(new_label)
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                flash(
                    f'Could not add newly defined label "{label}" due to a database error. Please contact a system administrator.',
                    "error",
                )

    return matched


@admin.route("/edit_global_email_template/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_global_email_template(id):
    """
    Edit an existing EmailTemplate instance
    :param id:
    :return:
    """
    template: EmailTemplate = EmailTemplate.query.get_or_404(id)
    form: EditEmailTemplateForm = EditEmailTemplateForm(obj=template)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.global_email_templates")

    if form.validate_on_submit():
        label_list = create_new_email_template_labels(form)

        template.subject = form.subject.data
        template.html_body = form.html_body.data
        template.labels = label_list
        template.comment = form.comment.data

        template.last_edit_id = current_user.id
        template.last_edit_timestamp = datetime.now()

        try:
            log_db_commit(
                f"Edited global email template #{id} '{template.subject}'",
                user=current_user,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes because of a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url)

    action_url = url_for("admin.edit_global_email_template", id=id, url=url)

    return render_template_context(
        "admin/email_templates/edit.html",
        form=form,
        email_template=template,
        title="Edit email template",
        action_url=action_url,
    )


@admin.route("/activate_global_email_template/<int:id>")
@roles_required("root")
def activate_global_email_template(id):
    """
    Activate an EmailTemplate instance
    :param id:
    :return:
    """
    template: EmailTemplate = EmailTemplate.query.get_or_404(id)
    template.active = True

    try:
        log_db_commit(
            f"Activated global email template #{id} '{template.subject}'",
            user=current_user,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not activate this email template because of a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(redirect_url())


@admin.route("/deactivate_email_template/<int:id>")
@roles_required("root")
def deactivate_global_email_template(id):
    """
    Deactivate an EmailTemplate instance.
    The global fallback (tenant_id=None, pclass_id=None) cannot be deactivated.
    :param id:
    :return:
    """
    template: EmailTemplate = EmailTemplate.query.get_or_404(id)

    # Ensure at least one fallback instance of this template would active  with tenant_id=None and pclass_id=None
    fallback_count = (
        db.session.query(EmailTemplate)
        .filter(
            EmailTemplate.type == template.type,
            EmailTemplate.active.is_(True),
            EmailTemplate.tenant_id.is_(None),
            EmailTemplate.pclass_id.is_(None),
        )
        .count()
    )

    if fallback_count <= 1:
        flash(
            "Cannot deactivate this template because no global fallback would be active for this template type.",
            "error",
        )
        return redirect(redirect_url())

    template.active = False

    try:
        log_db_commit(
            f"Deactivated global email template #{id} '{template.subject}'",
            user=current_user,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not deactivate this email template because of a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(redirect_url())


@admin.route("/duplicate_global_email_template/<int:id>")
@roles_required("root")
def duplicate_global_email_template(id):
    """
    Duplicate an existing EmailTemplate, creating a new version.
    :param id:
    :return:
    """
    template: EmailTemplate = EmailTemplate.query.get_or_404(id)

    new_template = clone_email_template(
        template, template.pclass_id, template.tenant_id, current_user
    )

    try:
        db.session.add(new_template)
        log_db_commit(
            f"Duplicated global email template #{id} as new version #{new_template.version}",
            user=current_user,
        )
        flash(
            f"Email template duplicated successfully: new version is #{new_template.version}.",
            "success",
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not duplicate this email template because of a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(redirect_url())


@admin.route("/delete_global_email_template/<int:id>")
@roles_required("root")
def delete_global_email_template(id):
    """
    Delete an EmailTemplate instance.
    Cannot delete if it is the only instance of its type, or if it is the global fallback.
    :param id:
    :return:
    """
    template: EmailTemplate = EmailTemplate.query.get_or_404(id)

    # Ensure at least one fallback instance of this template would remain with tenant_id=None and pclass_id=None
    fallback_count = (
        db.session.query(EmailTemplate)
        .filter(
            EmailTemplate.type == template.type,
            EmailTemplate.active.is_(True),
            EmailTemplate.tenant_id.is_(None),
            EmailTemplate.pclass_id.is_(None),
        )
        .count()
    )

    if fallback_count <= 1:
        flash(
            "Cannot delete this template because no active global fallback would exist for this template type.",
            "error",
        )
        return redirect(redirect_url())

    title = "Delete email template"
    panel_title = f"Delete email template: <strong>{template.subject}</strong>"

    action_url = url_for(
        "admin.perform_delete_global_email_template", id=id, url=redirect_url()
    )
    message = (
        f"<p>Please confirm that you wish to delete the email template "
        f"<strong>{template.subject}</strong> (version {template.version}).</p>"
        f"<p>This action cannot be undone.</p>"
    )
    submit_label = "Delete template"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@admin.route("/perform_delete_global_email_template/<int:id>")
@roles_required("root")
def perform_delete_global_email_template(id):
    """
    Perform deletion of an EmailTemplate instance.
    :param id:
    :return:
    """
    template: EmailTemplate = EmailTemplate.query.get_or_404(id)

    url = request.args.get("url", url_for("admin.global_email_templates"))

    # Ensure at least one global fallback remains for this type
    fallback_count = (
        db.session.query(EmailTemplate)
        .filter(
            EmailTemplate.type == template.type,
            EmailTemplate.active.is_(True),
            EmailTemplate.tenant_id.is_(None),
            EmailTemplate.pclass_id.is_(None),
        )
        .count()
    )

    if fallback_count <= 1:
        flash(
            "Cannot delete this template because no active global fallback would exist for this template type.",
            "error",
        )
        return redirect(url)

    try:
        db.session.delete(template)
        log_db_commit(
            f"Deleted global email template #{id} '{template.subject}'",
            user=current_user,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not delete this email template because of a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url)
