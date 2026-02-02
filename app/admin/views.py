#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import json
import re
from datetime import date, datetime, timedelta
from functools import partial
from io import BytesIO
from itertools import chain as itertools_chain
from math import pi
from pathlib import Path
from typing import List, Dict, Tuple, Iterable, Union
from urllib.parse import urlsplit

from bokeh.embed import components
from bokeh.models import Label
from bokeh.plotting import figure
from celery import chain, group
from flask import current_app, redirect, url_for, flash, request, jsonify, session, stream_with_context, abort, send_file
from flask_security import login_required, roles_required, roles_accepted, current_user, login_user
from numpy import histogram
from sqlalchemy import or_, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import cast
from sqlalchemy.sql import func
from sqlalchemy.types import String
from werkzeug.datastructures import Headers
from werkzeug.wrappers import Response

import app.ajax as ajax
import app.shared.cloud_object_store.bucket_types as buckets
from . import admin
from .actions import estimate_CATS_load, availability_CSV_generator, pair_slots
from .forms import (
    GlobalConfigForm,
    AddResearchGroupForm,
    EditResearchGroupForm,
    AddDegreeTypeForm,
    EditDegreeTypeForm,
    AddDegreeProgrammeForm,
    EditDegreeProgrammeForm,
    AddModuleForm,
    EditModuleForm,
    AddTransferableSkillForm,
    EditTransferableSkillForm,
    AddSkillGroupForm,
    EditSkillGroupForm,
    AddProjectClassForm,
    EditProjectClassForm,
    EditProjectTextForm,
    AddPeriodDefinitionFormFactory,
    EditPeriodDefinitionFormFactory,
    AddSupervisorForm,
    EditSupervisorForm,
    EmailLogForm,
    AddMessageFormFactory,
    EditMessageFormFactory,
    ScheduleTypeForm,
    AddIntervalScheduledTask,
    AddCrontabScheduledTask,
    EditIntervalScheduledTask,
    EditCrontabScheduledTask,
    EditBackupOptionsForm,
    BackupManageForm,
    NewMatchFormFactory,
    RenameMatchFormFactory,
    CompareMatchFormFactory,
    UploadMatchForm,
    AddPresentationAssessmentFormFactory,
    EditPresentationAssessmentFormFactory,
    AddSessionForm,
    EditSessionForm,
    AddBuildingForm,
    EditBuildingForm,
    AddRoomForm,
    EditRoomForm,
    AvailabilityFormFactory,
    NewScheduleFormFactory,
    RenameScheduleFormFactory,
    UploadScheduleForm,
    AssignmentLimitForm,
    ImposeConstraintsScheduleFormFactory,
    LevelSelectorForm,
    AddFHEQLevelForm,
    EditFHEQLevelForm,
    PublicScheduleFormFactory,
    CompareScheduleFormFactory,
    AddAssetLicenseForm,
    EditAssetLicenseForm,
    AddProjectTagGroupForm,
    EditProjectTagGroupForm,
    AddProjectTagForm,
    EditProjectTagForm,
    EditSupervisorRolesForm,
    SelectMatchingYearFormFactory,
    EditBackupForm,
    ManualBackupForm,
    UploadFeedbackAssetForm,
    EditFeedbackAssetForm,
    AddFeedbackRecipeForm,
    EditFeedbackRecipeForm,
)
from ..cache import cache
from ..database import db
from ..limiter import limiter
from ..models import (
    MainConfig,
    User,
    FacultyData,
    ResearchGroup,
    DegreeType,
    DegreeProgramme,
    SkillGroup,
    TransferableSkill,
    ProjectClass,
    ProjectClassConfig,
    Supervisor,
    EmailLog,
    MessageOfTheDay,
    DatabaseSchedulerEntry,
    IntervalSchedule,
    CrontabSchedule,
    BackupRecord,
    TaskRecord,
    Notification,
    EnrollmentRecord,
    MatchingAttempt,
    MatchingRecord,
    LiveProject,
    SubmissionPeriodRecord,
    SubmissionPeriodDefinition,
    PresentationAssessment,
    PresentationSession,
    Room,
    Building,
    ScheduleAttempt,
    ScheduleSlot,
    SubmissionRecord,
    Module,
    FHEQ_Level,
    AssessorAttendanceData,
    GeneratedAsset,
    TemporaryAsset,
    SubmittedAsset,
    AssetLicense,
    SubmittedAssetDownloadRecord,
    GeneratedAssetDownloadRecord,
    SelectingStudent,
    EmailNotification,
    ProjectTagGroup,
    ProjectTag,
    SubmitterAttendanceData,
    MatchingRole,
    SubmissionAttachment,
    PeriodAttachment,
    validate_nonce,
    BackupLabel,
    FeedbackAsset,
    TemplateTag,
    FeedbackRecipe,
)
from ..shared.asset_tools import AssetCloudAdapter, AssetUploadManager
from ..shared.backup import (
    get_backup_config,
    set_backup_config,
    compute_current_backup_count,
    compute_current_backup_size,
    remove_backup,
    create_new_backup_labels,
)
from ..shared.context.global_context import render_template_context
from ..shared.context.matching import get_ready_to_match_data, get_matching_dashboard_data
from ..shared.context.rollover import get_rollover_data
from ..shared.conversions import is_integer
from ..shared.formatters import format_size
from ..shared.forms.queries import ScheduleSessionQuery
from ..shared.internal_redis import get_redis
from ..shared.sqlalchemy import get_count
from ..shared.utils import (
    get_current_year,
    home_dashboard,
    get_automatch_pclasses,
    redirect_url,
    get_main_config,
    home_dashboard_url,
)
from ..shared.validators import (
    validate_is_admin_or_convenor,
    validate_match_inspector,
    validate_using_assessment,
    validate_assessment,
    validate_schedule_inspector,
)
from ..task_queue import register_task, progress_update
from ..tools import ServerSideSQLHandler, ServerSideInMemoryHandler


@admin.route("/global_config", methods=["GET", "POST"])
@roles_required("root")
def global_config():
    """
    Edit global configurations for this app instance
    :return:
    """
    config: MainConfig = get_main_config()
    form: GlobalConfigForm = GlobalConfigForm(obj=config)

    if form.validate_on_submit():
        url = form.canvas_url.data
        r = None
        if url is not None:
            if not re.match(r"http(s?)\:", url):
                url = "http://" + url
            r = urlsplit(url)

        config.enable_canvas_sync = form.enable_canvas_sync.data
        config.canvas_url = r.geturl() if r is not None else None

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes because of a database error. Please contact a system administrator", "error")

        return home_dashboard()

    return render_template_context("admin/global_config.html", config_form=form)


@admin.route("/edit_groups")
@roles_required("root")
def edit_groups():
    """
    View function that handles listing of all registered research groups
    :return:
    """
    return render_template_context("admin/edit_groups.html")


@admin.route("/groups_ajax", methods=["POST"])
@roles_required("root")
def groups_ajax():
    """
    Ajax data point for Edit Groups view
    :return:
    """
    base_query = db.session.query(ResearchGroup)

    abbrv = {"search": ResearchGroup.abbreviation, "order": ResearchGroup.abbreviation, "search_collation": "utf8_general_ci"}
    active = {"order": ResearchGroup.active}
    name = {"search": ResearchGroup.name, "order": ResearchGroup.name, "search_collation": "utf8_general_ci"}
    colour = {"search": ResearchGroup.colour, "order": ResearchGroup.colour, "search_collation": "utf8_general_ci"}
    website = {"search": ResearchGroup.website, "order": ResearchGroup.website, "search_collation": "utf8_general_ci"}

    columns = {"abbrv": abbrv, "active": active, "name": name, "colour": colour, "website": website}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.admin.groups_data)


@admin.route("/add_group", methods=["GET", "POST"])
@roles_required("root")
def add_group():
    """
    View function to add a new research group
    :return:
    """
    form = AddResearchGroupForm(request.form)

    if form.validate_on_submit():
        url = form.website.data
        if not re.match(r"http(s?)\:", url):
            url = "http://" + url
        r = urlsplit(url)  # canonicalize

        group = ResearchGroup(
            abbreviation=form.abbreviation.data,
            name=form.name.data,
            colour=form.colour.data,
            website=r.geturl(),
            active=True,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            db.session.add(group)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not add this affiliation group because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.edit_groups"))

    return render_template_context("admin/edit_group.html", group_form=form, title="Add new affiliation")


@admin.route("/edit_group/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_group(id):
    """
    View function to edit an existing research group
    :param id:
    :return:
    """
    group = ResearchGroup.query.get_or_404(id)
    form = EditResearchGroupForm(obj=group)

    form.group = group

    if form.validate_on_submit():
        url = form.website.data
        if not re.match(r"http(s?)\:", url):
            url = "http://" + url
        r = urlsplit(url)  # canonicalize

        group.abbreviation = form.abbreviation.data
        group.name = form.name.data
        group.colour = form.colour.data
        group.website = r.geturl()
        group.last_edit_id = current_user.id
        group.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.edit_groups"))

    return render_template_context("admin/edit_group.html", group_form=form, group=group, title="Edit affiliation")


@admin.route("/activate_group/<int:id>")
@roles_required("root")
def activate_group(id):
    """
    View to make a research group active
    :param id:
    :return:
    """
    group = ResearchGroup.query.get_or_404(id)
    group.enable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not save changes because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/deactivate_group/<int:id>")
@roles_required("root")
def deactivate_group(id):
    """
    View to make a research group inactive
    :param id:
    :return:
    """
    group = ResearchGroup.query.get_or_404(id)
    group.disable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not save changes because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/edit_degrees_types")
@roles_required("root")
def edit_degree_types():
    """
    View for editing degree types
    :return:
    """
    return render_template_context("admin/degree_types/edit_degrees.html", subpane="degrees")


@admin.route("/edit_degree_programmes")
@roles_required("root")
def edit_degree_programmes():
    """
    View for editing degree programmes
    :return:
    """
    return render_template_context("admin/degree_types/edit_programmes.html", subpane="programmes")


@admin.route("/edit_modules")
@roles_required("root")
def edit_modules():
    """
    View for editing modules
    :return:
    """
    return render_template_context("admin/degree_types/edit_modules.html", subpane="modules")


@admin.route("/edit_levels")
@roles_required("root")
def edit_levels():
    """
    View for editing FHEQ levels
    :return:
    """
    return render_template_context("admin/degree_types/edit_levels.html", subpane="levels")


@admin.route("/edit_levels_ajax", methods=["POST"])
@roles_required("root")
def edit_levels_ajax():
    """
    AJAX data point for FHEQ levels table
    :return:
    """
    base_query = db.session.query(FHEQ_Level)

    name = {"search": FHEQ_Level.name, "order": FHEQ_Level.name, "search_collation": "utf8_general_ci"}
    short_name = {"search": FHEQ_Level.short_name, "order": FHEQ_Level.short_name, "search_collation": "utf8_general_ci"}
    colour = {"search": FHEQ_Level.colour, "order": FHEQ_Level.colour, "search_collation": "utf8_general_ci"}
    numeric_level = {"order": FHEQ_Level.numeric_level, "search": cast(FHEQ_Level.numeric_level, String)}
    status = {"order": FHEQ_Level.active}

    columns = {"name": name, "short_name": short_name, "colour": colour, "numeric_level": numeric_level, "status": status}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.admin.FHEQ_levels_data)


@admin.route("/degree_types_ajax", methods=["POST"])
@roles_required("root")
def degree_types_ajax():
    """
    Ajax data point for degree type table
    :return:
    """
    base_query = db.session.query(DegreeType)

    name = {"search": DegreeType.name, "order": DegreeType.name, "search_collation": "utf8_general_ci"}
    level = {"order": DegreeType.level}
    duration = {"search": cast(DegreeType.duration, String), "order": DegreeType.duration}
    colour = {"search": DegreeType.colour, "order": DegreeType.colour, "search_collation": "utf8_general_ci"}
    active = {"order": DegreeType.active}

    columns = {"name": name, "level": level, "duration": duration, "colour": colour, "active": active}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.admin.degree_types_data)


@admin.route("/degree_programmes_ajax", methods=["POST"])
@roles_required("root")
def degree_programmes_ajax():
    """
    Ajax data point for degree programmes tables
    :return:
    """
    base_query = db.session.query(DegreeProgramme).join(DegreeType, DegreeType.id == DegreeProgramme.type_id)

    name = {"search": DegreeProgramme.name, "order": DegreeProgramme.name, "search_collation": "utf8_general_ci"}
    type = {"search": DegreeType.name, "order": DegreeType.name, "search_collation": "utf8_general_ci"}
    show_type = {"order": DegreeProgramme.show_type}
    course_code = {"search": DegreeProgramme.course_code, "order": DegreeProgramme.course_code, "search_collation": "utf8_general_ci"}
    active = {"order": DegreeProgramme.active}

    columns = {"name": name, "type": type, "show_type": show_type, "course_code": course_code, "active": active}

    levels = db.session.query(FHEQ_Level).filter_by(active=True).order_by(FHEQ_Level.numeric_level.asc()).all()

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(partial(ajax.admin.degree_programmes_data, levels))


@admin.route("/modules_ajax", methods=["POST"])
@roles_required("root")
def modules_ajax():
    """
    Ajax data point for module table
    :return:
    """
    base_query = db.session.query(Module).join(FHEQ_Level, FHEQ_Level.id == Module.level_id)

    code = {"search": Module.code, "order": Module.code, "search_collation": "utf8_general_ci"}
    name = {"search": Module.name, "order": Module.name, "search_collation": "utf8_general_ci"}
    level = {"search": FHEQ_Level.short_name, "order": FHEQ_Level.short_name, "search_collation": "utf8_general_ci"}
    status = {"order": Module.active}

    columns = {"code": code, "name": name, "level": level, "status": status}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.admin.modules_data)


@admin.route("/add_type", methods=["GET", "POST"])
@roles_required("root")
def add_degree_type():
    """
    View to create a new degree type
    :return:
    """
    form = AddDegreeTypeForm(request.form)

    if form.validate_on_submit():
        degree_type = DegreeType(
            name=form.name.data,
            abbreviation=form.abbreviation.data,
            colour=form.colour.data,
            duration=form.duration.data,
            level=form.level.data,
            active=True,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            db.session.add(degree_type)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not add a degree type because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.edit_degree_types"))

    return render_template_context("admin/degree_types/edit_degree.html", type_form=form, title="Add new degree type")


@admin.route("/edit_type/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_degree_type(id):
    """
    View to edit a degree type
    :param id:
    :return:
    """
    type = DegreeType.query.get_or_404(id)
    form = EditDegreeTypeForm(obj=type)

    form.degree_type = type

    if form.validate_on_submit():
        type.name = form.name.data
        type.abbreviation = form.abbreviation.data
        type.colour = form.colour.data
        type.duration = form.duration.data
        type.level = form.level.data
        type.last_edit_id = current_user.id
        type.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.edit_degree_types"))

    return render_template_context("admin/degree_types/edit_degree.html", type_form=form, type=type, title="Edit degree type")


@admin.route("/make_type_active/<int:id>")
@roles_required("root")
def activate_degree_type(id):
    """
    Make a degree type active
    :param id:
    :return:
    """

    degree_type = DegreeType.query.get_or_404(id)
    degree_type.enable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not save changes because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/make_type_inactive/<int:id>")
@roles_required("root")
def deactivate_degree_type(id):
    """
    Make a degree type inactive
    :param id:
    :return:
    """

    degree_type = DegreeType.query.get_or_404(id)
    degree_type.disable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not save changes because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/add_programme", methods=["GET", "POST"])
@roles_required("root")
def add_degree_programme():
    """
    View to create a new degree programme
    :return:
    """
    # check whether any active degree types exist, and raise an error if not
    if not DegreeType.query.filter_by(active=True).first():
        flash("No degree types are available. Set up at least one active degree type before adding a degree programme.", "error")
        return redirect(redirect_url())

    form = AddDegreeProgrammeForm(request.form)

    if form.validate_on_submit():
        degree_type = form.degree_type.data
        programme = DegreeProgramme(
            name=form.name.data,
            abbreviation=form.abbreviation.data,
            show_type=form.show_type.data,
            foundation_year=form.foundation_year.data,
            year_out=form.year_out.data,
            year_out_value=form.year_out_value.data if form.year_out.data else None,
            course_code=form.course_code.data,
            active=True,
            type_id=degree_type.id,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            db.session.add(programme)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not add a degree programme because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.edit_degree_programmes"))

    return render_template_context("admin/degree_types/edit_programme.html", programme_form=form, title="Add new degree programme")


@admin.route("/edit_programme/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_degree_programme(id):
    """
    View to edit a degree programme
    :param id:
    :return:
    """

    programme: DegreeProgramme = DegreeProgramme.query.get_or_404(id)
    form: EditDegreeProgrammeForm = EditDegreeProgrammeForm(obj=programme)

    form.programme = programme

    if form.validate_on_submit():
        programme.name = form.name.data
        programme.abbreviation = form.abbreviation.data
        programme.show_type = form.show_type.data
        programme.course_code = form.course_code.data
        programme.foundation_year = form.foundation_year.data
        programme.year_out = form.year_out.data
        programme.year_out_value = form.year_out_value.data if programme.year_out else None
        programme.type_id = form.degree_type.data.id
        programme.last_edit_id = current_user.id
        programme.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.edit_degree_programmes"))

    return render_template_context("admin/degree_types/edit_programme.html", programme_form=form, programme=programme, title="Edit degree programme")


@admin.route("/activate_programme/<int:id>")
@roles_required("root")
def activate_degree_programme(id):
    """
    Make a degree programme active
    :param id:
    :return:
    """
    programme: DegreeProgramme = DegreeProgramme.query.get_or_404(id)
    programme.enable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not save changes because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/deactivate_programme/<int:id>")
@roles_required("root")
def deactivate_degree_programme(id):
    """
    Make a degree programme inactive
    :param id:
    :return:
    """
    programme: DegreeProgramme = DegreeProgramme.query.get_or_404(id)
    programme.disable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not save changes because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/attach_modules/<int:id>/<int:level_id>", methods=["GET", "POST"])
@admin.route("/attach_modules/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def attach_modules(id, level_id=None):
    """
    Attach modules to a degree programme
    :param id:
    :return:
    """
    programme: DegreeProgramme = DegreeProgramme.query.get_or_404(id)

    form = LevelSelectorForm(request.form)

    if not form.validate_on_submit() and request.method == "GET":
        if level_id is None:
            form.selector.data = FHEQ_Level.query.filter(FHEQ_Level.active == True).order_by(FHEQ_Level.numeric_level.asc()).first()
        else:
            form.selector.data = FHEQ_Level.query.filter(FHEQ_Level.active == True, FHEQ_Level.id == level_id).first()

    # get list of modules for the current level_id
    if form.selector.data is not None:
        modules = Module.query.filter(Module.active == True, Module.level_id == form.selector.data.id).order_by(
            Module.semester.asc(), Module.name.asc()
        )
    else:
        modules = []

    level_id = form.selector.data.id if form.selector.data is not None else None

    levels = FHEQ_Level.query.filter_by(active=True).order_by(FHEQ_Level.numeric_level.asc()).all()

    return render_template_context(
        "admin/degree_types/attach_modules.html", prog=programme, modules=modules, form=form, level_id=level_id, levels=levels, title="Attach modules"
    )


@admin.route("/attach_module/<int:prog_id>/<int:mod_id>/<int:level_id>")
@roles_required("root")
def attach_module(prog_id, mod_id, level_id):
    """
    Attach a module to a degree programme
    :param prog_id:
    :param mod_id:
    :return:
    """
    programme: DegreeProgramme = DegreeProgramme.query.get_or_404(prog_id)
    module: Module = Module.query.get_or_404(mod_id)

    if module not in programme.modules:
        programme.modules.append(module)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes because of a database error. Please contact a system administrator", "error")

    return redirect(url_for("admin.attach_modules", id=prog_id, level_id=level_id))


@admin.route("/detach_module/<int:prog_id>/<int:mod_id>/<int:level_id>")
@roles_required("root")
def detach_module(prog_id, mod_id, level_id):
    """
    Detach a module from a degree programme
    :param prog_id:
    :param mod_id:
    :return:
    """
    programme = DegreeProgramme.query.get_or_404(prog_id)
    module = Module.query.get_or_404(mod_id)

    if module in programme.modules:
        programme.modules.remove(module)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes because of a database error. Please contact a system administrator", "error")

    return redirect(url_for("admin.attach_modules", id=prog_id, level_id=level_id))


@admin.route("/add_level", methods=["GET", "POST"])
@roles_required("root")
def add_level():
    """
    Add a new FHEQ level record
    :return:
    """
    form = AddFHEQLevelForm(request.form)

    if form.validate_on_submit():
        level = FHEQ_Level(
            name=form.name.data,
            short_name=form.short_name.data,
            numeric_level=form.numeric_level.data,
            colour=form.colour.data,
            active=True,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
            last_edit_id=None,
            last_edit_timestamp=None,
        )

        try:
            db.session.add(level)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could add a FHEQ level because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.edit_levels"))

    return render_template_context("admin/degree_types/edit_level.html", form=form, title="Add new FHEQ Level")


@admin.route("/edit_level/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_level(id):
    """
    Edit an existing FHEQ level record
    :return:
    """
    level = FHEQ_Level.query.get_or_404(id)
    form = EditFHEQLevelForm(obj=level)
    form.level = level

    if form.validate_on_submit():
        level.name = form.name.data
        level.short_name = form.short_name.data
        level.numeric_level = form.numeric_level.data
        level.colour = form.colour.data
        level.last_edit_id = current_user.id
        level.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.edit_levels"))

    return render_template_context("admin/degree_types/edit_level.html", form=form, level=level, title="Edit FHEQ Level")


@admin.route("/activate_level/<int:id>")
@roles_accepted("root")
def activate_level(id):
    """
    Make an FHEQ level active
    :param id:
    :return:
    """
    level = FHEQ_Level.query.get_or_404(id)
    level.enable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not save changes because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/deactivate_level/<int:id>")
@roles_accepted("root")
def deactivate_level(id):
    """
    Make an FHEQ level inactive
    :param id:
    :return:
    """
    skill = FHEQ_Level.query.get_or_404(id)
    skill.disable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not save changes because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/add_module", methods=["GET", "POST"])
@roles_required("root")
def add_module():
    """
    Add a new module record
    :return:
    """
    # check whether any active FHEQ levels exist, and raise an error if not
    if not FHEQ_Level.query.filter_by(active=True).first():
        flash("No FHEQ Levels are available. Set up at least one active FHEQ Level before adding a module.", "error")
        return redirect(redirect_url())

    form = AddModuleForm(request.form)

    if form.validate_on_submit():
        module = Module(
            code=form.code.data,
            name=form.name.data,
            level=form.level.data,
            semester=form.semester.data,
            first_taught=get_current_year(),
            last_taught=None,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
            last_edit_id=None,
            last_edit_timestamp=None,
        )

        try:
            db.session.add(module)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not add a module because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.edit_modules"))

    return render_template_context("admin/degree_types/edit_module.html", form=form, title="Add new module")


@admin.route("/edit_module/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_module(id):
    """
    id labels a Module
    :param id:
    :return:
    """
    module = Module.query.get_or_404(id)

    if not module.active:
        flash('Module "{code} {name}" cannot be edited because it is ' "retired.".format(code=module.code, name=module.name), "info")
        return redirect(redirect_url())

    form = EditModuleForm(obj=module)
    form.module = module

    if form.validate_on_submit():
        module.code = form.code.data
        module.name = form.name.data
        module.level = form.level.data
        module.semester = form.semester.data
        module.last_edit_id = current_user.id
        module.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.edit_modules"))

    return render_template_context("admin/degree_types/edit_module.html", form=form, title="Edit module", module=module)


@admin.route("/retire_module/<int:id>")
@roles_required("root")
def retire_module(id):
    """
    Retire a current module
    :param id:
    :return:
    """
    module = Module.query.get_or_404(id)
    module.retire()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not save changes because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/unretire_module/<int:id>")
@roles_required("root")
def unretire_module(id):
    """
    Un-retire a current module
    :param id:
    :return:
    """
    module = Module.query.get_or_404(id)
    module.unretire()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not save changes because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/edit_skills")
@roles_accepted("admin", "root", "faculty", "edit_tags")
def edit_skills():
    """
    View for edit skills
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    return render_template_context("admin/transferable_skills/edit_skills.html", subpane="skills")


@admin.route("/skills_ajax", methods=["POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def skills_ajax():
    """
    Ajax data point for transferable skills table
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return jsonify({})

    base_query = db.session.query(TransferableSkill).join(SkillGroup, SkillGroup.id == TransferableSkill.group_id)

    name = {"search": TransferableSkill.name, "order": TransferableSkill.name, "search_collation": "utf8_general_ci"}
    group = {"search": SkillGroup.name, "order": SkillGroup.name, "search_collation": "utf8_general_ci"}
    active = {"order": TransferableSkill.active}

    columns = {"name": name, "group": group, "active": active}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.admin.skills.skills_data)


@admin.route("/add_skill", methods=["GET", "POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def add_skill():
    """
    View to create a new transferable skill
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    # check whether any skill groups exist, and raise an error if not
    if not db.session.query(SkillGroup).filter_by(active=True).first():
        flash("No skill groups are available. Set up at least one active skill group before adding a transferable skill.", "error")
        return redirect(redirect_url())

    form = AddTransferableSkillForm(request.form)

    if form.validate_on_submit():
        skill = TransferableSkill(
            name=form.name.data, group=form.group.data, active=True, creator_id=current_user.id, creation_timestamp=datetime.now()
        )

        try:
            db.session.add(skill)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not add this skill group because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.edit_skills"))

    return render_template_context("admin/transferable_skills/edit_skill.html", skill_form=form, title="Add new transferable skill")


@admin.route("/edit_skill/<int:id>", methods=["GET", "POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def edit_skill(id):
    """
    View to edit a transferable skill
    :param id:
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    skill = TransferableSkill.query.get_or_404(id)
    form = EditTransferableSkillForm(obj=skill)

    form.skill = skill

    if form.validate_on_submit():
        skill.name = form.name.data
        skill.group = form.group.data
        skill.last_edit_id = current_user.id
        skill.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.edit_skills"))

    return render_template_context("admin/transferable_skills/edit_skill.html", skill_form=form, skill=skill, title="Edit transferable skill")


@admin.route("/activate_skill/<int:id>")
@roles_accepted("admin", "root", "faculty", "edit_tags")
def activate_skill(id):
    """
    Make a transferable skill active
    :param id:
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    skill = TransferableSkill.query.get_or_404(id)
    skill.enable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not activate this transferable skill because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/deactivate_skill/<int:id>")
@roles_accepted("admin", "root", "faculty", "edit_tags")
def deactivate_skill(id):
    """
    Make a transferable skill inactive
    :param id:
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    skill = TransferableSkill.query.get_or_404(id)
    skill.disable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not deactivate this transferable skill because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/edit_skill_groups")
@roles_accepted("admin", "root", "faculty", "edit_tags")
def edit_skill_groups():
    """
    View for editing skill groups
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    return render_template_context("admin/transferable_skills/edit_skill_groups.html", subpane="groups")


@admin.route("/skill_groups_ajax", methods=["POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def skill_groups_ajax():
    """
    Ajax data point for skill groups table
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return jsonify({})

    base_query = db.session.query(SkillGroup)

    name = {"search": SkillGroup.name, "order": SkillGroup.name, "search_collation": "utf8_general_ci"}
    include = {"order": SkillGroup.add_group}
    active = {"order": SkillGroup.active}

    columns = {"name": name, "include": include, "active": active}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.admin.skill_groups.skill_groups_data)


@admin.route("/add_skill_group", methods=["GET", "POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def add_skill_group():
    """
    Add a new skill group
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    form = AddSkillGroupForm(request.form)

    if form.validate_on_submit():
        group = SkillGroup(
            name=form.name.data,
            colour=form.colour.data,
            add_group=form.add_group.data,
            active=True,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            db.session.add(group)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not add new transferable skill group because of a database error. Please contact a system administrator.", "error")

        return redirect(url_for("admin.edit_skill_groups"))

    return render_template_context("admin/transferable_skills/edit_skill_group.html", group_form=form, title="Add new transferable skill group")


@admin.route("/edit_skill_group/<int:id>", methods=["GET", "POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def edit_skill_group(id):
    """
    Edit an existing skill group
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    group = SkillGroup.query.get_or_404(id)
    form = EditSkillGroupForm(obj=group)

    form.group = group

    if form.validate_on_submit():
        group.name = form.name.data
        group.colour = form.colour.data
        group.add_group = form.add_group.data
        group.last_edit_id = current_user.id
        group.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes because of a database error. Please contact a system administrator.", "error")

        return redirect(url_for("admin.edit_skill_groups"))

    return render_template_context(
        "admin/transferable_skills/edit_skill_group.html", group=group, group_form=form, title="Edit transferable skill group"
    )


@admin.route("/activate_skill_group/<int:id>")
@roles_accepted("admin", "root", "faculty", "edit_tags")
def activate_skill_group(id):
    """
    Make a transferable skill group active
    :param id:
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    group = SkillGroup.query.get_or_404(id)
    group.enable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not activate this skill group because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/deactivate_skill_group/<int:id>")
@roles_accepted("admin", "root", "faculty", "edit_tags")
def deactivate_skill_group(id):
    """
    Make a transferable skill group inactive
    :param id:
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    group = SkillGroup.query.get_or_404(id)
    group.disable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not deactivate this skill group because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/edit_project_tag_groups")
@roles_accepted("admin", "root", "faculty", "edit_tags")
def edit_project_tag_groups():
    """
    Project tag group list
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    return render_template_context("admin/project_tags/edit_tag_groups.html", subpane="groups")


@admin.route("/edit_project_tag_groups_ajax", methods=["POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def edit_project_tag_groups_ajax():
    """
    AJAX endpoint for project tag groups table
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return jsonify({})

    base_query = db.session.query(ProjectTagGroup)

    name = {"search": ProjectTagGroup.name, "order": ProjectTagGroup.name, "search_collation": "utf8_general_ci"}
    include = {"order": ProjectTagGroup.add_group}
    active = {"order": ProjectTagGroup.active}

    columns = {"name": name, "include": include, "active": active}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.admin.project_tag_groups.tag_groups_data)


@admin.route("/add_project_tag_group", methods=["GET", "POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def add_project_tag_group():
    """
    Add a new project tag group
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    form: AddProjectTagGroupForm = AddProjectTagGroupForm(request.form)

    if form.validate_on_submit():
        group = ProjectTagGroup(
            name=form.name.data,
            add_group=form.add_group.data,
            default=form.default.data,
            active=True,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            # unset default from all other groups, if this one is the new defaut
            if group.default:
                db.session.execute(update(ProjectTagGroup).values(default=False))

            db.session.add(group)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not add new project tag group because of a database error. Please contact a system administrator.", "error")

        return redirect(url_for("admin.edit_project_tag_groups"))

    return render_template_context("admin/project_tags/edit_tag_group.html", group_form=form, title="Add new project tag group")


@admin.route("/edit_project_tag_group/<int:gid>", methods=["GET", "POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def edit_project_tag_group(gid):
    """
    Edit an existing project tag group
    :param gid:
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    group: ProjectTagGroup = ProjectTagGroup.query.get_or_404(gid)
    form: EditProjectTagGroupForm = EditProjectTagGroupForm(obj=group)

    form.group = group
    form.was_default = group.default

    if form.validate_on_submit():
        group.name = form.name.data
        group.add_group = form.add_group.data
        group.default = form.default.data
        group.last_edit_id = current_user.id
        group.last_edit_timestamp = datetime.now()

        try:
            if group.default and not form.was_default:
                db.session.execute(update(ProjectTagGroup).where(ProjectTagGroup.id != group.id).values(default=False))

            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes because of a database error. Please contact a system administrator.", "error")

        return redirect(url_for("admin.edit_project_tag_groups"))

    return render_template_context("admin/project_tags/edit_tag_group.html", group=group, group_form=form, title="Edit project tag group")


@admin.route("/activate_project_tag_group/<int:gid>")
@roles_accepted("admin", "root", "faculty", "edit_tags")
def activate_project_tag_group(gid):
    """
    Make a project tag group active
    :param gid:
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    group: ProjectTagGroup = ProjectTagGroup.query.get_or_404(gid)
    group.enable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not activate this project tag group because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/deactivate_project_tag_group/<int:gid>")
@roles_accepted("admin", "root", "faculty", "edit_tags")
def deactivate_project_tag_group(gid):
    """
    Make a project tag group inactive
    :param gid:
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    group: ProjectTagGroup = ProjectTagGroup.query.get_or_404(gid)

    if group.default:
        flash("Cannot disable this project tag group becuase it is currently the default group for new tags", "info")
        return redirect(redirect_url())

    group.disable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not disable this project tag group because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/edit_project_tags")
@roles_accepted("admin", "root", "faculty", "edit_tags")
def edit_project_tags():
    """
    Project tags list
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    return render_template_context("admin/project_tags/edit_tags.html", subpane="tags")


@admin.route("edit_project_tags_ajax", methods=["POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def edit_project_tags_ajax():
    """
    AJAX endpoint for project tags table
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return jsonify({})

    base_query = db.session.query(ProjectTag).join(ProjectTagGroup, ProjectTagGroup.id == ProjectTag.group_id)

    name = {"search": ProjectTag.name, "order": ProjectTag.name, "search_collation": "utf8_general_ci"}
    group = {"search": ProjectTagGroup.name, "order": ProjectTagGroup.name, "search_collation": "utf8_general_ci"}
    active = {"order": ProjectTag.active}

    columns = {"name": name, "group": group, "active": active}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.admin.project_tags.tags_data)


@admin.route("/add_project_tag", methods=["GET", "POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def add_project_tag():
    """
    Create a new project tag
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    # check whether any ProjectTagGroups exist, and raise an error if not
    if not db.session.query(ProjectTagGroup).filter_by(active=True).first():
        flash("No project tag groups are available. Set up at least one active tag group before adding a tag.", "error")
        return redirect(redirect_url())

    form: AddProjectTagForm = AddProjectTagForm(request.form)

    if form.validate_on_submit():
        tag = ProjectTag(
            name=form.name.data,
            group=form.group.data,
            colour=form.colour.data,
            active=True,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        if isinstance(tag.colour, str) and len(tag.colour) == 0:
            tag.colour = None

        try:
            db.session.add(tag)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not add this project tag because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.edit_project_tags"))

    return render_template_context("admin/project_tags/edit_tag.html", tag_form=form, title="Add new project tag")


@admin.route("/edit_project_tag/<int:tid>", methods=["GET", "POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def edit_project_tag(tid):
    """
    Edit an existing project tag
    :param tid:
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    tag: ProjectTag = ProjectTag.query.get_or_404(tid)
    form: EditProjectTagForm = EditProjectTagForm(obj=tag)

    form.tag = tag

    if form.validate_on_submit():
        tag.name = form.name.data
        tag.group = form.group.data
        tag.colour = form.colour.data
        tag.last_edit_id = current_user.id
        tag.last_edit_timestamp = datetime.now()

        if isinstance(tag.colour, str) and len(tag.colour) == 0:
            tag.colour = None

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.edit_project_tags"))

    return render_template_context("admin/project_tags/edit_tag.html", tag=tag, tag_form=form, title="Edit project tag")


@admin.route("/activate_project_tag/<int:tid>")
@roles_accepted("admin", "root", "faculty", "edit_tags")
def activate_project_tag(tid):
    """
    Make a project tag active
    :param tid:
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    tag: ProjectTag = ProjectTag.query.get_or_404(tid)
    tag.enable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not activate this project tag because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/deactivate_project_tag/<int:tid>")
@roles_accepted("admin", "root", "faculty", "edit_tags")
def deactivate_project_tag(tid):
    """
    Make a project tag inactive
    :param tid:
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    tag: ProjectTag = ProjectTag.query.get_or_404(tid)
    tag.disable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not disable this project tag because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/edit_licenses")
@roles_required("root")
def edit_licenses():
    """
    Provide list and edit view for content licneses
    :return:
    """
    return render_template_context("admin/edit_licenses.html")


@admin.route("/licenses_ajax")
@roles_required("root")
def licenses_ajax():
    """
    AJAX data entry point for content licenses table
    :return:
    """
    licenses = db.session.query(AssetLicense).all()
    return ajax.admin.licenses_data(licenses)


@admin.route("/add_license", methods=["GET", "POST"])
@roles_required("root")
def add_license():
    """
    Create a new license
    :return:
    """
    form = AddAssetLicenseForm(request.form)

    if form.validate_on_submit():
        data = AssetLicense(
            name=form.name.data,
            abbreviation=form.abbreviation.data,
            colour=form.colour.data,
            description=form.description.data,
            version=form.version.data,
            url=form.url.data,
            allows_redistribution=form.allows_redistribution.data,
            active=True,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            db.session.add(data)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not add new license because of a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.edit_licenses"))

    return render_template_context("admin/edit_license.html", form=form, title="Add new content license")


@admin.route("/edit_license/<int:lid>", methods=["GET", "POST"])
@roles_required("root")
def edit_license(lid):
    """
    Edit an existing license
    :param lid:
    :return:
    """
    license = AssetLicense.query.get_or_404(lid)
    form = EditAssetLicenseForm(obj=license)

    form.license = license

    if form.validate_on_submit():
        license.name = form.name.data
        license.abbreviation = form.abbreviation.data
        license.colour = form.colour.data
        license.description = form.description.data
        license.version = form.version.data
        license.url = form.url.data
        license.allows_redistribution = form.allows_redistribution.data

        license.last_edit_id = current_user.id
        license.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                'Could not edit license "{name}" because of a database error. ' "Please contact a system administrator".format(name=license.name),
                "error",
            )

        return redirect(url_for("admin.edit_licenses"))

    return render_template_context("admin/edit_license.html", form=form, title="Edit content license", license=license)


@admin.route("/activate_license/<int:lid>")
@roles_required("root")
def activate_license(lid):
    """
    Make a license active
    :param lid:
    :return:
    """
    license = AssetLicense.query.get_or_404(lid)
    license.enable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            'Could not activate license "{name}" due to a database error. ' "Please contact a system administrator".format(name=license.name), "error"
        )

    return redirect(redirect_url())


@admin.route("/activate_license/<int:lid>")
@roles_required("root")
def deactivate_license(lid):
    """
    Make a license active
    :param lid:
    :return:
    """
    license = AssetLicense.query.get_or_404(lid)
    license.disable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            'Could not deactivate license "{name}" due to a database error. ' "Please contact a system administrator".format(name=license.name),
            "error",
        )

    return redirect(redirect_url())


@admin.route("/edit_project_classes")
@roles_required("root")
def edit_project_classes():
    """
    Provide list and edit view for project classes
    :return:
    """
    return render_template_context("admin/edit_project_classes.html")


@admin.route("/pclasses_ajax")
@roles_required("root")
def pclasses_ajax():
    """
    Ajax data point for project class tables
    :return:
    """
    classes = ProjectClass.query.all()
    return ajax.admin.pclasses_data(classes)


@admin.route("/add_pclass", methods=["GET", "POST"])
@roles_required("root")
def add_pclass():
    """
    Create a new project class
    :return:
    """
    # check whether any active degree types exist, and raise an error if not
    if not DegreeType.query.filter_by(active=True).first():
        flash("No degree types are available. Set up at least one active degree type before adding a project class.")
        return redirect(redirect_url())

    form: AddProjectClassForm = AddProjectClassForm(request.form)

    if form.validate_on_submit():
        # make sure convenor and coconvenors don't have overlap
        coconvenors = form.coconvenors.data
        if form.convenor.data in coconvenors:
            coconvenors.remove(form.convenor.data)

        try:
            # insert a record for this project class
            data = ProjectClass(
                name=form.name.data,
                abbreviation=form.abbreviation.data,
                colour=form.colour.data,
                do_matching=form.do_matching.data,
                number_assessors=form.number_assessors.data,
                use_project_hub=form.use_project_hub.data,
                student_level=form.student_level.data,
                is_optional=form.is_optional.data,
                uses_selection=form.uses_selection.data,
                uses_submission=form.uses_submission.data,
                start_year=form.start_year.data,
                extent=form.extent.data,
                require_confirm=form.require_confirm.data,
                supervisor_carryover=form.supervisor_carryover.data,
                include_available=form.include_available.data,
                uses_supervisor=form.uses_supervisor.data,
                uses_marker=form.uses_marker.data,
                uses_moderator=form.uses_moderator.data,
                uses_presentations=form.uses_presentations.data,
                display_marker=form.display_marker.data,
                display_presentations=form.display_presentations.data,
                reenroll_supervisors_early=form.reenroll_supervisors_early.data,
                convenor=form.convenor.data,
                coconvenors=coconvenors,
                office_contacts=form.office_contacts.data,
                approvals_team=form.approvals_team.data,
                select_in_previous_cycle=form.select_in_previous_cycle.data,
                selection_open_to_all=form.selection_open_to_all.data,
                auto_enrol_enable=form.auto_enrol_enable.data,
                auto_enroll_years=form.auto_enroll_years.data,
                programmes=form.programmes.data,
                initial_choices=form.initial_choices.data,
                allow_switching=form.allow_switching.data,
                switch_choices=form.switch_choices.data,
                faculty_maximum=form.faculty_maximum.data,
                active=True,
                CATS_supervision=form.CATS_supervision.data,
                CATS_marking=form.CATS_marking.data,
                CATS_moderation=form.CATS_moderation.data,
                CATS_presentation=form.CATS_presentation.data,
                keep_hourly_popularity=form.keep_hourly_popularity.data,
                keep_daily_popularity=form.keep_daily_popularity.data,
                advertise_research_group=form.advertise_research_group.data,
                use_project_tags=form.use_project_tags.data,
                force_tag_groups=form.force_tag_groups.data,
                card_text_noninitial=None,
                card_text_normal=None,
                card_text_optional=None,
                email_text_draft_match_preamble=None,
                email_text_final_match_preamble=None,
                creator_id=current_user.id,
                creation_timestamp=datetime.now(),
            )
            db.session.add(data)
            db.session.flush()
            data.convenor.add_convenorship(data)

            # generate a corresponding configuration record for the current academic year
            current_year = get_current_year()

            config = ProjectClassConfig(
                year=current_year,
                pclass_id=data.id,
                convenor_id=data.convenor_id,
                uses_supervisor=form.uses_supervisor.data,
                uses_marker=form.uses_marker.data,
                uses_moderator=form.uses_moderator.data,
                uses_presentations=form.uses_presentations.data,
                display_marker=form.display_marker.data,
                display_presentations=form.display_presentations.data,
                requests_issued=False,
                requests_issued_id=None,
                requests_timestamp=None,
                request_deadline=None,
                requests_skipped=False,
                requests_skipped_id=None,
                requests_skipped_timestamp=None,
                use_project_hub=form.use_project_hub.data,
                live=False,
                selection_closed=False,
                CATS_supervision=data.CATS_supervision,
                CATS_marking=data.CATS_marking,
                CATS_moderation=data.CATS_moderation,
                CATS_presentation=data.CATS_presentation,
                creator_id=current_user.id,
                creation_timestamp=datetime.now(),
                submission_period=1,
                canvas_module_id=None,
                canvas_login_id=None,
            )
            db.session.add(config)
            db.session.flush()

            # generate submission period records, if any
            # if this is a brand new project then we won't create anything -- that will have to be done
            # later, when the submission periods are defined
            if data.uses_submission:
                for t in config.template_periods.all():
                    period = SubmissionPeriodRecord(
                        config_id=config.id,
                        name=t.name,
                        number_markers=t.number_markers,
                        number_moderators=t.number_moderators,
                        start_date=t.start_date,
                        has_presentation=t.has_presentation,
                        lecture_capture=t.lecture_capture,
                        collect_presentation_feedback=t.collect_presentation_feedback,
                        collect_project_feedback=t.collect_project_feedback,
                        number_assessors=t.number_assessors,
                        max_group_size=t.max_group_size,
                        morning_session=t.morning_session,
                        afternoon_session=t.afternoon_session,
                        talk_format=t.talk_format,
                        retired=False,
                        submission_period=t.period,
                        feedback_open=False,
                        feedback_id=None,
                        feedback_timestamp=None,
                        feedback_deadline=None,
                        closed=False,
                        closed_id=None,
                        closed_timestamp=None,
                        canvas_module_id=None,
                        canvas_assignment_id=None,
                    )
                    db.session.add(period)

            db.session.flush()
            modified: bool = data.validate_presentations()
            db.session.commit()

        except SQLAlchemyError as e:
            flash("Could not create new project class because of a database error. Please contact a system administrator.", "error")
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        flash('Set convenor for "{title}" to {name}.'.format(name=data.convenor_name, title=data.name))

        return redirect(url_for("admin.edit_project_classes"))

    else:
        if request.method == "GET":
            form.number_assessors.data = current_app.config["DEFAULT_ASSESSORS"]
            form.require_confirm.data = True
            form.uses_supervisor.data = True
            form.uses_marker.data = True
            form.uses_presentations.data = False
            form.display_marker.data = True
            form.display_presentations.data = True
            form.auto_enroll_years.data = ProjectClass.AUTO_ENROLL_FIRST_YEAR
            form.is_optional.data = False
            form.uses_selection.data = True
            form.uses_submission.data = True
            form.do_matching.data = True
            form.allow_switching = False
            form.advertise_research_group.data = True
            form.use_project_tags.data = False
            form.force_tag_groups.data = []

    return render_template_context("admin/edit_project_class.html", pclass_form=form, title="Add new project class")


@admin.route("/edit_pclass/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_pclass(id):
    """
    Edit properties for an existing project class
    :param id:
    :return:
    """
    data: ProjectClass = ProjectClass.query.get_or_404(id)
    form: EditProjectClassForm = EditProjectClassForm(obj=data)

    form.project_class = data

    # remember old convenor
    old_convenor: FacultyData = data.convenor

    if form.validate_on_submit():
        # make sure convenor and coconvenors don't have overlap
        coconvenors = form.coconvenors.data
        if form.convenor.data in coconvenors:
            coconvenors.remove(form.convenor.data)

        data.name = form.name.data
        data.abbreviation = form.abbreviation.data
        data.use_project_hub = form.use_project_hub.data
        data.student_level = form.student_level.data
        data.start_year = form.start_year.data
        data.colour = form.colour.data
        data.is_optional = form.is_optional.data
        data.uses_selection = form.uses_selection.data
        data.uses_submission = form.uses_submission.data
        data.do_matching = form.do_matching.data
        data.number_assessors = form.number_assessors.data
        data.extent = form.extent.data
        data.require_confirm = form.require_confirm.data
        data.supervisor_carryover = form.supervisor_carryover.data
        data.include_available = form.include_available.data
        data.uses_supervisor = form.uses_supervisor.data
        data.uses_marker = form.uses_marker.data
        data.uses_moderator = form.uses_moderator.data
        data.uses_presentations = form.uses_presentations.data
        data.display_marker = form.display_marker.data
        data.display_presentations = form.display_presentations.data
        data.reenroll_supervisors_early = form.reenroll_supervisors_early.data
        data.convenor = form.convenor.data
        data.coconvenors = coconvenors
        data.office_contacts = form.office_contacts.data
        data.approvals_team = form.approvals_team.data
        data.select_in_previous_cycle = form.select_in_previous_cycle.data
        data.selection_open_to_all = form.selection_open_to_all.data
        data.auto_enrol_enable = form.auto_enrol_enable.data
        data.auto_enroll_years = form.auto_enroll_years.data
        data.advertise_research_group = form.advertise_research_group.data
        data.use_project_tags = form.use_project_tags.data
        data.force_tag_groups = form.force_tag_groups.data
        data.programmes = form.programmes.data
        data.initial_choices = form.initial_choices.data
        data.allow_switching = form.allow_switching.data
        data.switch_choices = form.switch_choices.data
        data.faculty_maximum = form.faculty_maximum.data
        data.CATS_supervision = form.CATS_supervision.data
        data.CATS_marking = form.CATS_marking.data
        data.CATS_moderation = form.CATS_moderation.data
        data.CATS_presentation = form.CATS_presentation.data
        data.keep_hourly_popularity = form.keep_hourly_popularity.data
        data.keep_daily_popularity = form.keep_daily_popularity.data
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        if data.convenor.id != old_convenor.id:
            old_convenor.remove_convenorship(data)
            data.convenor.add_convenorship(data)

        try:
            db.session.flush()
            modified: bool = data.validate_presentations()
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("Could not save project class configuration because of a database error. Please check the logs for further information.", "error")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        if data.convenor.id != old_convenor.id:
            flash(
                'Set convenor for "{title}" to {name}. The previous convenor was {oldname} and has been '
                "removed".format(name=data.convenor_name, oldname=old_convenor.user.name, title=data.name)
            )

        return redirect(url_for("admin.edit_project_classes"))

    else:
        if request.method == "GET":
            if form.number_assessors.data is None:
                form.number_assessors.data = current_app.config["DEFAULT_ASSESSORS"]

            if form.require_confirm.data is None:
                form.require_confirm.data = True

            if form.uses_supervisor.data is None:
                form.uses_supervisor.data = True

            if form.uses_marker.data is None:
                form.uses_marker.data = True

            if form.uses_presentations.data is None:
                form.uses_presentations.data = False

            if form.display_marker.data is None:
                form.display_marker.data = True

            if form.display_presentations.data is None:
                form.display_presentations = True

            if form.auto_enroll_years.data is None:
                form.auto_enroll_years.data = ProjectClass.AUTO_ENROLL_FIRST_YEAR

            if form.is_optional.data is None:
                form.is_optional.data = False

            if form.uses_selection.data is None:
                form.uses_selection.data = True

            if form.uses_submission.data is None:
                form.uses_submission.data = True

            if form.do_matching.data is None:
                form.do_matching.data = True

            if form.advertise_research_group.data is None:
                form.advertise_research_group.data = True

            if form.use_project_tags.data is None:
                form.use_project_tags.data = False

            if form.force_tag_groups.data is None:
                form.force_tag_groups.data = []

    return render_template_context("admin/edit_project_class.html", pclass_form=form, pclass=data, title="Edit project class")


@admin.route("/edit_pclass_text/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_pclass_text(id):
    data = ProjectClass.query.get_or_404(id)

    form = EditProjectTextForm(obj=data)

    if form.validate_on_submit():
        data.card_text_normal = form.card_text_normal.data
        data.card_text_optional = form.card_text_optional.data
        data.card_text_noninitial = form.card_text_noninitial.data
        data.email_text_draft_match_preamble = form.email_text_draft_match_preamble.data
        data.email_text_final_match_preamble = form.email_text_final_match_preamble.data

        db.session.commit()

        return redirect(url_for("admin.edit_project_classes"))

    return render_template_context("admin/edit_pclass_text.html", form=form, pclass=data)


@admin.route("/activate_pclass/<int:id>")
@roles_required("root")
def activate_pclass(id):
    """
    Make a project class active
    :param id:
    :return:
    """
    data = ProjectClass.query.get_or_404(id)
    data.enable()
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/deactivate_pclass/<int:id>")
@roles_required("root")
def deactivate_pclass(id):
    """
    Make a project class inactive
    :param id:
    :return:
    """
    data = ProjectClass.query.get_or_404(id)
    data.disable()
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/publish_pclass/<int:id>")
@roles_required("root")
def publish_pclass(id):
    """
    Set a project class as 'published'
    :param id:
    :return:
    """
    data = ProjectClass.query.get_or_404(id)
    data.set_published()
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/unpublish_pclass/<int:id>")
@roles_required("root")
def unpublish_pclass(id):
    """
    Set a project class as 'unpublished'
    :param id:
    :return:
    """
    data = ProjectClass.query.get_or_404(id)
    data.set_unpublished()
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/edit_period_definitions/<int:id>")
@roles_required("root")
def edit_period_definitions(id):
    """
    Set up submission periods for a given project class
    incorporated
    :param id:
    :return:
    """
    data = ProjectClass.query.get_or_404(id)
    return render_template_context("admin/edit_period_definitions.html", pclass=data)


@admin.route("/period_definitions_ajax/<int:id>")
@roles_required("root")
def period_definitions_ajax(id):
    """
    Return AJAX data for the submission periods table
    :param id:
    :return:
    """

    data = ProjectClass.query.get_or_404(id)
    periods = data.periods.all()

    return ajax.admin.periods_data(periods)


@admin.route("/regenerate_submission_periods/<int:id>")
@roles_required("root")
def regenerate_period_records(id):
    """
    Generate a new (if needed) set of SubmissionPeriodRecords corresponding to the current
    snapshot of SubmissionPeriodDefinitions
    :param id:
    :return:
    """

    # get current set of submission period definitions and validate
    data: ProjectClass = ProjectClass.query.get_or_404(id)

    # validate periods (ensure there is at least on period definition record, and that all definition
    # records have continuous ascending serial numbers)
    modified: bool = data.validate_periods()
    if modified:
        db.session.flush()

    # get current set of submission period records and templates
    current_year = get_current_year()
    config = data.get_config(current_year)

    templates = config.template_periods.all()
    records = config.periods.order_by(SubmissionPeriodRecord.submission_period.asc()).all()

    # work through existing recrods and templates in pairs, overwriting each record with the content
    # of the corresponding template
    while len(records) > 0:
        t = templates.pop(0)
        c = records.pop(0)

        c.submission_period = t.period
        c.name = t.name
        c.start_date = t.start_date
        c.has_presentation = t.has_presentation
        c.lecture_capture = t.lecture_capture
        c.collect_presentation_feedback = t.collect_presentation_feedback
        c.collect_project_feedback = t.collect_project_feedback
        c.number_assessors = t.number_assessors
        c.max_group_size = t.max_group_size
        c.morning_session = t.morning_session
        c.afternoon_session = t.afternoon_session
        c.talk_format = t.talk_format

    # do we need to generate new records?
    while len(templates) > 0:
        t = templates.pop(0)

        period = SubmissionPeriodRecord(
            config_id=config.id,
            name=t.name,
            number_markers=t.number_markers,
            number_moderators=t.number_moderators,
            start_date=t.start_date,
            has_presentation=t.has_presentation,
            lecture_capture=t.lecture_capture,
            collect_presentation_feedback=t.collect_presentation_feedback,
            collect_project_feedback=t.collect_project_feedback,
            number_assessors=t.number_assessors,
            max_group_size=t.max_group_size,
            morning_session=t.morning_session,
            afternoon_session=t.afternoon_session,
            talk_format=t.talk_format,
            retired=False,
            submission_period=t.period,
            feedback_open=False,
            feedback_id=None,
            feedback_timestamp=None,
            feedback_deadline=None,
            closed=False,
            closed_id=None,
            closed_timestamp=None,
            canvas_module_id=None,
            canvas_assignment_id=None,
        )
        db.session.add(period)

        # add SubmissionRecord instances for any attached students
        for sel in config.submitting_students:
            sub_record = SubmissionRecord(
                period_id=period.id,
                retired=False,
                owner_id=sel.id,
                project_id=None,
                selection_config_id=None,
                matching_record_id=None,
                student_engaged=False,
                use_project_hub=None,
                report_id=None,
                processed_report_id=None,
                celery_started=False,
                celery_finished=False,
                timestamp=False,
                report_exemplar=False,
                report_embargo=False,
                report_secret=False,
                exemplar_comment=None,
                supervision_grade=None,
                report_grade=None,
                grade_generated_id=None,
                grade_generated_timestamp=None,
                canvas_submission_available=False,
                turnitin_outcome=None,
                turnitin_score=None,
                turnitin_web_overlap=None,
                turnitin_publication_overlap=None,
                turnitin_student_overlap=None,
                feedback_generated=False,
                feedback_sent=False,
                feedback_push_id=None,
                feedback_push_timestamp=None,
                student_feedback=None,
                student_feedback_submitted=None,
                student_feedback_timestamp=None,
            )
            db.session.add(sub_record)

    while len(records) > 0:
        c = records.pop(0)

        # remove any attached SubmissionRecords
        db.session.query(SubmissionRecord).filter_by(period_id=c.id, retired=False).delete()
        db.session.delete(c)

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash(
            "Could not update submission period records for this project class due to a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
    else:
        flash("Successfully updated submission period records for this project class", "info")

    return redirect(redirect_url())


@admin.route("/add_period_definition/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def add_period_definition(id):
    """
    Add a new submission period configuration to the given project class
    :param id:
    :return:
    """
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)
    AddPeriodDefinitionForm = AddPeriodDefinitionFormFactory(pclass)
    form = AddPeriodDefinitionForm(form=request.form)

    if form.validate_on_submit():
        if form.has_presentation.data:
            pd = SubmissionPeriodDefinition(
                owner_id=pclass.id,
                period=pclass.number_submissions + 1,
                name=form.name.data,
                number_markers=form.number_markers.data,
                number_moderators=form.number_moderators.data,
                start_date=form.start_date.data,
                has_presentation=True,
                lecture_capture=form.lecture_capture.data,
                number_assessors=form.number_assessors.data,
                collect_presentation_feedback=form.collect_presentation_feedback.data,
                collect_project_feedback=form.collect_project_feedback.data,
                max_group_size=form.max_group_size.data,
                morning_session=form.morning_session.data,
                afternoon_session=form.afternoon_session.data,
                talk_format=form.talk_format.data,
                creator_id=current_user.id,
                creation_timestamp=datetime.now(),
            )

        else:
            pd = SubmissionPeriodDefinition(
                owner_id=pclass.id,
                period=pclass.number_submissions + 1,
                name=form.name.data,
                number_markers=form.number_markers.data,
                number_moderators=form.number_moderators.data,
                start_date=form.start_date.data,
                has_presentation=False,
                lecture_capture=False,
                number_assessors=None,
                collect_presentation_feedback=False,
                collect_project_feedback=True,
                max_group_size=None,
                morning_session=None,
                afternoon_session=None,
                talk_format=None,
                creator_id=current_user.id,
                creation_timestamp=datetime.now(),
            )

        pclass.periods.append(pd)

        try:
            db.session.flush()
            modified: bool = pclass.validate_presentations()
            db.session.commit()
        except SQLAlchemyError as e:
            flash("Could not add new submission period definition because of a database error. Please contact a system administrator.", "error")
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("admin.edit_period_definitions", id=pclass.id))

    return render_template_context("admin/edit_period_definition.html", form=form, pclass_id=pclass.id, title="Add new submission period")


@admin.route("/edit_period_definition/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_period_definition(id):
    """
    Edit an existing submission period configuration
    :param id:
    :return:
    """
    pd: SubmissionPeriodDefinition = SubmissionPeriodDefinition.query.get_or_404(id)
    EditPeriodDefinitionForm = EditPeriodDefinitionFormFactory(pd.owner)
    form = EditPeriodDefinitionForm(obj=pd)

    if form.validate_on_submit():
        pd.name = form.name.data
        pd.number_markers = form.number_markers.data
        pd.number_moderators = form.number_moderators.data
        pd.start_date = form.start_date.data
        pd.has_presentation = form.has_presentation.data

        if pd.has_presentation:
            pd.lecture_capture = form.lecture_capture.data
            pd.collect_presentation_feedback = form.collect_presentation_feedback.data
            pd.collect_project_feedback = form.collect_project_feedback.data
            pd.number_assessors = form.number_assessors.data
            pd.max_group_size = form.max_group_size.data
            pd.morning_session = form.morning_session.data
            pd.afternoon_session = form.afternoon_session.data
            pd.talk_format = form.talk_format.data

        else:
            pd.lecture_capture = False
            pd.collect_presentation_feedback = False
            pd.collect_project_feedback = True
            pd.number_assessors = None
            pd.max_group_size = None
            pd.morning_session = None
            pd.afternoon_session = None
            pd.talk_format = None

        pd.last_edit_id = (current_user.id,)
        pd.last_edit_timestamp = datetime.now()

        try:
            db.session.flush()
            modified: bool = pd.owner.validate_presentations()
            db.session.commit()
        except SQLAlchemyError as e:
            flash("Could not save changes because of a database error. Please contact a system administrator.", "error")
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("admin.edit_period_definitions", id=pd.owner.id))

    return render_template_context("admin/edit_period_definition.html", form=form, period=pd, title="Edit submission period")


@admin.route("/delete_period_definition/<int:id>")
@roles_required("root")
def delete_period_definition(id):
    """
    Delete a submission period configuration
    :param id:
    :return:
    """

    data = SubmissionPeriodDefinition.query.get_or_404(id)
    pclass = data.owner

    try:
        db.session.delete(data)
        db.session.flush()
        modified: bool = pclass.validate_presentations()
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not delete submission period definition because of a database error. Please contact a system administrator.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/edit_supervisors")
@roles_accepted("admin", "root", "faculty", "edit_tags")
def edit_supervisors():
    """
    View to list and edit supervisory roles
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    return render_template_context("admin/edit_supervisors.html")


@admin.route("/supervisors_ajax", methods=["POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def supervisors_ajax():
    """
    Ajax datapoint for supervisors table
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    base_query = db.session.query(Supervisor)

    role = {"search": Supervisor.name, "order": Supervisor.name, "search_collation": "utf8_general_ci"}
    active = {"order": Supervisor.active}

    columns = {"role": role, "active": active}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.admin.supervisors_data)


@admin.route("/add_supervisor", methods=["GET", "POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def add_supervisor():
    """
    Create a new supervisory role
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    form = AddSupervisorForm(request.form)

    if form.validate_on_submit():
        data = Supervisor(
            name=form.name.data,
            abbreviation=form.abbreviation.data,
            colour=form.colour.data,
            active=True,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )
        try:
            db.session.add(data)
            db.session.commit()
        except SQLAlchemyError as e:
            flash("Could not add new supervisory team member definition because of a database error. Please contact a system administrator.", "error")
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("admin.edit_supervisors"))

    return render_template_context("admin/edit_supervisor.html", supervisor_form=form, title="Add new supervisory role")


@admin.route("/edit_supervisor/<int:id>", methods=["GET", "POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def edit_supervisor(id):
    """
    Edit a supervisory role
    :param id:
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    data = Supervisor.query.get_or_404(id)
    form = EditSupervisorForm(obj=data)

    form.supervisor = data

    if form.validate_on_submit():
        data.name = form.name.data
        data.abbreviation = form.abbreviation.data
        data.colour = form.colour.data
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash("Could not save changes because of a database error. Please contact a system administrator.", "error")
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("admin.edit_supervisors"))

    return render_template_context("admin/edit_supervisor.html", supervisor_form=form, role=data, title="Edit supervisory role")


@admin.route("/activate_supervisor/<int:id>")
@roles_accepted("admin", "root", "faculty", "edit_tags")
def activate_supervisor(id):
    """
    Make a supervisor active
    :param id:
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    data = Supervisor.query.get_or_404(id)
    data.enable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not activate supervisory team member because of a database error. Please contact a system administrator.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/deactivate_supervisor/<int:id>")
@roles_accepted("admin", "root", "faculty", "edit_tags")
def deactivate_supervisor(id):
    """
    Make a supervisor inactive
    :param id:
    :return:
    """

    if not validate_is_admin_or_convenor("edit_tags"):
        return home_dashboard()

    data = Supervisor.query.get_or_404(id)
    data.disable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not deactivate supervisory team member because of a database error. Please contact a system administrator.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/confirm_global_rollover")
@roles_required("root")
def confirm_global_rollover():
    """
    Show confirmation box for global advance of academic year
    :return:
    """
    data = get_rollover_data()

    if not data["rollover_ready"]:
        flash("Can not initiate a rollover of the academic year because no project classes are ready", "info")
        return redirect(redirect_url())

    if data["rollover_in_progress"]:
        flash("Can not initiate a rollover of the academic year because one is already in progress", "info")
        return redirect(redirect_url())

    next_year = get_current_year() + 1

    title = "Global rollover to {yeara}&ndash;{yearb}".format(yeara=next_year, yearb=next_year + 1)
    panel_title = "Global rollover of academic year to {yeara}&ndash;{yearb}".format(yeara=next_year, yearb=next_year + 1)
    action_url = url_for("admin.perform_global_rollover")
    message = (
        "<p><strong>Please confirm that you wish to advance the global academic year to "
        "{yeara}&ndash;{yearb}.</strong></p>"
        '<p class="mt-1">No project classes will be modified. Project class rollover must be initiated '
        "by individual module convenors.</p>"
        '<p class="mt-1">After the current academic year has been incremented, '
        "a routine database maintenance process will be "
        "run.</p>"
        '<p class="mt-2">This action cannot be undone.</p>'.format(yeara=next_year, yearb=next_year + 1)
    )
    submit_label = "Rollover to {yra}&ndash;{yrb}".format(yra=next_year, yrb=next_year + 1)

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/perform_global_rollover")
@roles_required("root")
def perform_global_rollover():
    """
    Globally advance the academic year
    (doesn't actually do anything directly; the complex parts of rollover are done
    for each project class at a time decided by its convenor or an administrator)
    :return:
    """
    data = get_rollover_data()
    current_config = get_main_config()

    if not data["rollover_ready"]:
        flash("Can not initiate a rollover of the academic year because no project classes are ready", "info")
        return redirect(redirect_url())

    if data["rollover_in_progress"]:
        flash("Can not initiate a rollover of the academic year because one is already in progress", "info")
        return redirect(redirect_url())

    current_year = get_current_year()
    next_year = current_year + 1

    try:
        # insert new MainConfig instance for next year, rolling over most current settings
        new_year = MainConfig(year=next_year, enable_canvas_sync=current_config.enable_canvas_sync, canvas_url=current_config.canvas_url)
        db.session.add(new_year)
        db.session.commit()

    except SQLAlchemyError as e:
        flash("Could not complete rollover due to database error. Please check the logs.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    else:
        tk_name = "Perform global rollover to academic year {yra}-{yrb}".format(yra=next_year, yrb=next_year + 1)
        tk_description = "Perform global rollover"
        uuid = register_task(tk_name, owner=current_user, description=tk_description)

        celery = current_app.extensions["celery"]

        init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
        final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
        error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

        # need to perform a maintenance cycle to update students' academic years
        maintenance_cycle = celery.tasks["app.tasks.maintenance.maintenance"]

        # TODO: pruning of matching attempts must now be scheduled elsewhere in the lifecycle --
        #  this has still to be done

        # schedule all parts of the rollover+maintenance cycle
        seq = chain(init.si(uuid, tk_name), maintenance_cycle.si(), final.si(uuid, tk_name, current_user.id)).on_error(
            error.si(uuid, tk_name, current_user.id)
        )
        seq.apply_async(task_id=uuid)

    return home_dashboard()


@admin.route("/email_log")
@roles_accepted("root", "view_email")
def email_log():
    """
    Display a log of sent emails
    :return:
    """
    if current_user.has_role("root"):
        form = EmailLogForm(request.form)
    else:
        form = None

    if form is not None and form.validate_on_submit():
        if form.delete_age.data is True:
            return redirect(url_for("admin.confirm_delete_email_cutoff", cutoff=(form.weeks.data)))

    return render_template_context("admin/email_log.html", form=form)


@limiter.exempt
@admin.route("/email_log_ajax", methods=["POST"])
@roles_accepted("root", "view_email")
def email_log_ajax():
    """
    Ajax data point for email log
    :return:
    """
    base_query = db.session.query(EmailLog)

    # set up columns for server-side processing
    recipient = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "search_collection": EmailLog.recipients,
        "search_collation": "utf8_general_ci",
    }
    address = {"search": User.email, "search_collection": EmailLog.recipients, "search_collation": "utf8_general_ci"}
    date = {"search": func.date_format(EmailLog.send_date, "%a %d %b %Y %H:%M:%S"), "order": EmailLog.send_date}
    subject = {"search": EmailLog.subject, "order": EmailLog.subject, "search_collaboration": "utf8_general_ci"}

    columns = {"recipient": recipient, "address": address, "date": date, "subject": subject}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.site.email_log_data)


@admin.route("/display_email/<int:id>")
@roles_accepted("root", "view_email")
def display_email(id):
    """
    Display a specific email
    :param id:
    :return:
    """
    email = EmailLog.query.get_or_404(id)

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    if text is None and url is None:
        url = url_for("admin.email_log")
        text = "email log"

    return render_template_context("admin/display_email.html", email=email, text=text, url=url)


@admin.route("/delete_email/<int:id>")
@roles_required("root")
def delete_email(id):
    """
    Delete an email
    :param id:
    :return:
    """
    email = EmailLog.query.get_or_404(id)

    try:
        db.session.delete(email)
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not delete email because of a database error. Please contact a system administrator.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url_for("admin.email_log"))


@admin.route("/confirm_delete_all_emails")
@roles_required("root")
def confirm_delete_all_emails():
    """
    Show confirmation box to delete all emails
    :return:
    """

    title = "Confirm delete"
    panel_title = "Confirm delete of all emails retained in log"

    action_url = url_for("admin.delete_all_emails")
    message = "<p>Please confirm that you wish to delete all emails retained in the log.</p>" "<p>This action cannot be undone.</p>"
    submit_label = "Delete all"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/delete_all_emails")
@roles_required("root")
def delete_all_emails():
    """
    Delete all emails stored in the log
    :return:
    """

    # hand off job to asynchronous task backend since potentially long-running on a big database
    celery = current_app.extensions["celery"]
    delete_email = celery.tasks["app.tasks.prune_email.delete_all_email"]

    tk_name = "Manual delete email"
    tk_description = "Manually delete all email"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(init.si(task_id, tk_name), delete_email.si(), final.si(task_id, tk_name, current_user.id)).on_error(
        error.si(task_id, tk_name, current_user.id)
    )
    seq.apply_async(task_id=task_id)

    return redirect(url_for("admin.email_log"))


@admin.route("/confirm_delete_email_cutoff/<int:cutoff>")
@roles_required("root")
def confirm_delete_email_cutoff(cutoff):
    """
    Show confirmation box to delete emails with a cutoff
    :return:
    """

    pl = "s"
    if cutoff == 1:
        pl = ""

    title = "Confirm delete"
    panel_title = "Confirm delete all emails older than {c} week{pl}".format(c=cutoff, pl=pl)

    action_url = url_for("admin.delete_email_cutoff", cutoff=cutoff)
    message = "<p>Please confirm that you wish to delete all emails older than {c} week{pl}.</p>" "<p>This action cannot be undone.</p>".format(
        c=cutoff, pl=pl
    )
    submit_label = "Delete"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/delete_email_cutoff/<int:cutoff>")
@roles_required("root")
def delete_email_cutoff(cutoff):
    """
    Delete all emails older than the given cutoff
    :param cutoff:
    :return:
    """

    pl = "s"
    if cutoff == 1:
        pl = ""

    # hand off job to asynchronous task backend since potentially long-running on a big database
    celery = current_app.extensions["celery"]
    prune_email = celery.tasks["app.tasks.prune_email.prune_email_log"]

    tk_name = "Manual delete email"
    tk_description = "Manually delete email older than {c} week{pl}".format(c=cutoff, pl=pl)
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(init.si(task_id, tk_name), prune_email.si(duration=cutoff, interval="weeks"), final.si(task_id, tk_name, current_user.id)).on_error(
        error.si(task_id, tk_name, current_user.id)
    )
    seq.apply_async(task_id=task_id)

    return redirect(url_for("admin.email_log"))


@admin.route("/scheduled_email")
@roles_accepted("root", "view_email")
def scheduled_email():
    """
    Display scheduled outgoing email
    :return:
    """
    return render_template_context("admin/scheduled_email.html")


@admin.route("/scheduled_email_ajax", methods=["POST"])
@roles_accepted("root", "view_email")
def scheduled_email_ajax():
    """
    AJAX data point for scheduled email list
    :return:
    """
    base_query = db.session.query(EmailNotification).join(User, User.id == EmailNotification.owner_id)

    recipient = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "order": [User.last_name, User.first_name],
        "search_collation": "utf8_general_ci",
    }
    timestamp = {"search": func.date_format(EmailNotification.timestamp, "%a %d %b %Y %H:%M:%S"), "order": EmailNotification.timestamp}
    type = {"order": EmailNotification.event_type}

    columns = {"recipient": recipient, "timestamp": timestamp, "type": type}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.site.scheduled_email)


@admin.route("/hold_notification/<int:eid>")
@roles_accepted("root", "view_email")
def hold_notification(eid):
    """
    Mark an outgoing notification as held
    :return:
    """
    notification: EmailNotification = EmailNotification.query.get_or_404(eid)

    notification.held = True

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not mark notification as held because of a database error. Please contact a system administrator.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/release_notification/<int:eid>")
@roles_accepted("root", "view_email")
def release_notification(eid):
    """
    Mark an outgoing notification as not held (released)
    :return:
    """
    notification: EmailNotification = EmailNotification.query.get_or_404(eid)

    notification.held = False

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not mark notification as released because of a database error. Please contact a system administrator.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/delete_notification/<int:eid>")
@roles_accepted("root", "view_email")
def delete_notification(eid):
    """
    Mark an outgoing notification as held
    :return:
    """
    notification: EmailNotification = EmailNotification.query.get_or_404(eid)

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    title = "Confirm delete"
    panel_title = "Confirm delete scheduled notification"

    action_url = url_for("admin.do_delete_notification", eid=eid)
    message = (
        "<p>Please confirm that you wish to delete a scheduled email notification to "
        '<i class="fas fa-user-circle"></i> <strong>{name}</strong></p>'
        "<p>This action cannot be undone.</p>".format(name=notification.owner.name)
    )
    submit_label = "Delete"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label, url=url
    )


@admin.route("/do_delete_notification/<int:eid>")
@roles_accepted("root", "view_email")
def do_delete_notification(eid):
    """
    Delete an email notification
    :return:
    """
    notification: EmailNotification = EmailNotification.query.get_or_404(eid)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.scheduled_email")

    try:
        db.session.delete(notification)
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not delete notification because of a database error. Please contact a system administrator.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@admin.route("/edit_messages")
@roles_accepted("faculty", "admin", "root")
def edit_messages():
    """
    Edit message-of-the-day type messages
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    return render_template_context("admin/edit_messages.html")


@admin.route("/messages_ajax")
@roles_accepted("faculty", "admin", "root")
def messages_ajax():
    """
    Ajax data point for message-of-the-day list
    :return:
    """

    if not validate_is_admin_or_convenor():
        return jsonify({})

    if current_user.has_role("admin") or current_user.has_role("root"):
        # admin users can edit all messages
        messages = MessageOfTheDay.query.all()

    else:
        # convenors can only see their own messages
        messages = MessageOfTheDay.query.filter_by(user_id=current_user.id).all()

    return ajax.admin.messages_data(messages)


@admin.route("/add_message", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def add_message():
    """
    Add a new message-of-the-day message
    :return:
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    # convenors can't show login-screen messages
    if not current_user.has_role("admin") and not current_user.has_role("root"):
        AddMessageForm = AddMessageFormFactory(convenor_editing=True)
        form = AddMessageForm(request.form)
    else:
        AddMessageForm = AddMessageFormFactory(convenor_editing=False)
        form = AddMessageForm(request.form)

    if form.validate_on_submit():
        if "show_login" in form._fields:
            show_login = form._fields.get("show_login").data
        else:
            show_login = False

        data = MessageOfTheDay(
            user_id=current_user.id,
            issue_date=datetime.now(),
            show_students=form.show_students.data,
            show_faculty=form.show_faculty.data,
            show_office=form.show_office.data,
            show_login=show_login,
            dismissible=form.dismissible.data,
            title=form.title.data,
            body=form.body.data,
            project_classes=form.project_classes.data,
        )
        db.session.add(data)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash("Could not add message because of a database error. Please contact a system administrator.", "error")
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("admin.edit_messages"))

    return render_template_context("admin/edit_message.html", form=form, title="Add new broadcast message")


@admin.route("/edit_message/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_message(id):
    """
    Edit a message-of-the-day message
    :return:
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    data: MessageOfTheDay = MessageOfTheDay.query.get_or_404(id)

    # convenors can't show login-screen messages and can only edit their own messages
    if not current_user.has_role("admin") and not current_user.has_role("root"):
        if data.user_id != current_user.id:
            flash("Only administrative users can edit messages that they do not own")
            return home_dashboard()

        EditMessageForm = EditMessageFormFactory(convenor_editing=True)
        form = EditMessageForm(obj=data)

    else:
        EditMessageForm = EditMessageFormFactory(convenor_editing=False)
        form = EditMessageForm(obj=data)

    if form.validate_on_submit():
        if "show_login" in form._fields:
            show_login = form._fields.get("show_login").data
        else:
            show_login = False

        data.show_students = form.show_students.data
        data.show_faculty = form.show_faculty.data
        data.show_office = form.show_office.data
        data.show_login = show_login
        data.dismissible = form.dismissible.data
        data.title = form.title.data
        data.body = form.body.data
        data.project_classes = form.project_classes.data

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash("Could not save edited message because of a database error. Please contact a system administrator.", "error")
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("admin.edit_messages"))

    return render_template_context("admin/edit_message.html", message=data, form=form, title="Edit broadcast message")


@admin.route("/delete_message/<int:id>")
@roles_accepted("faculty", "admin", "root")
def delete_message(id):
    """
    Delete message-of-the-day message
    :return:
    """

    if not validate_is_admin_or_convenor():
        return home_dashboard()

    data = MessageOfTheDay.query.get_or_404(id)

    # convenors can only delete their own messages
    if not current_user.has_role("admin") and not current_user.has_role("root"):
        if data.user_id != current_user.id:
            flash("Only administrative users can edit messages that are not their own.")
            return home_dashboard()

    db.session.delete(data)
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/dismiss_message/<int:id>")
@login_required
def dismiss_message(id):
    """
    Record that the current user has dismissed a particular message
    :param id:
    :return:
    """

    message = MessageOfTheDay.query.get_or_404(id)

    if current_user not in message.dismissed_by:
        message.dismissed_by.append(current_user)
        db.session.commit()

    return redirect(redirect_url())


@admin.route("/reset_dismissals/<int:id>")
@roles_accepted("faculty", "admin", "root")
def reset_dismissals(id):
    """
    Remove dismissals from a message (eg. we might want to do this after updating the text)
    :param id:
    :return:
    """

    message = MessageOfTheDay.query.get_or_404(id)

    # convenors can only reset their own messages
    if not current_user.has_role("admin") and not current_user.has_role("root"):
        if message.user_id != current_user.id:
            flash("Only administrative users can reset dismissals for messages that are not their own.")
            return home_dashboard()

    message.dismissed_by = []
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/scheduled_tasks")
@roles_required("root")
def scheduled_tasks():
    """
    UI for scheduling periodic tasks (database backup, prune email log, etc.)
    :return:
    """

    return render_template_context("admin/scheduled_tasks.html")


@admin.route("/scheduled_ajax")
@roles_required("root")
def scheduled_ajax():
    """
    Ajax data source for scheduled periodic tasks
    :return:
    """

    tasks = db.session.query(DatabaseSchedulerEntry).all()
    return ajax.site.scheduled_task_data(tasks)


@admin.route("/add_scheduled_task", methods=["GET", "POST"])
@roles_required("root")
def add_scheduled_task():
    """
    Add a new scheduled task
    :return:
    """

    form = ScheduleTypeForm(request.form)

    if form.validate_on_submit():
        if form.type.data == "interval":
            return redirect(url_for("admin.add_interval_task"))

        elif form.type.data == "crontab":
            return redirect(url_for("admin.add_crontab_task"))

        else:
            flash("The task type was not recognized. If this error persists, please contact the system administrator.")
            return redirect(url_for("admin.scheduled_tasks"))

    return render_template_context("admin/scheduled_type.html", form=form, title="Select schedule type")


@admin.route("/add_interval_task", methods=["GET", "POST"])
@roles_required("root")
def add_interval_task():
    """
    Add a new task specified by a simple interval
    :return:
    """

    form = AddIntervalScheduledTask(request.form)

    if form.validate_on_submit():
        # build or lookup an appropriate IntervalSchedule record from the database
        sch = IntervalSchedule.query.filter_by(every=form.every.data, period=form.period.data).first()

        if sch is None:
            sch = IntervalSchedule(every=form.every.data, period=form.period.data)
            db.session.add(sch)
            db.session.flush()

        args = json.loads(form.arguments.data)
        kwargs = json.loads(form.keyword_arguments.data)
        now = datetime.now()

        data = DatabaseSchedulerEntry(
            name=form.name.data,
            owner_id=form.owner.data.id,
            task=form.task.data,
            interval_id=sch.id,
            crontab_id=None,
            args=args,
            kwargs=kwargs,
            queue=form.queue.data,
            exchange=None,
            routing_key=None,
            expires=form.expires.data,
            enabled=True,
            last_run_at=now,
            total_run_count=0,
            date_changed=now,
        )

        db.session.add(data)
        db.session.commit()

        return redirect(url_for("admin.scheduled_tasks"))

    return render_template_context("admin/edit_scheduled_task.html", form=form, title="Add new fixed-interval task")


@admin.route("/add_crontab_task", methods=["GET", "POST"])
@roles_required("root")
def add_crontab_task():
    """
    Add a new task specified by a crontab
    :return:
    """

    form = AddCrontabScheduledTask(request.form)

    if form.validate_on_submit():
        # build or lookup an appropriate IntervalSchedule record from the database
        sch = CrontabSchedule.query.filter_by(
            minute=form.minute.data,
            hour=form.hour.data,
            day_of_week=form.day_of_week.data,
            day_of_month=form.day_of_month.data,
            month_of_year=form.month_of_year.data,
        ).first()

        if sch is None:
            sch = CrontabSchedule(
                minute=form.minute.data,
                hour=form.hour.data,
                day_of_week=form.day_of_week.data,
                day_of_month=form.day_of_month.data,
                month_of_year=form.month_of_year.data,
            )
            db.session.add(sch)
            db.session.flush()

        args = json.loads(form.arguments.data)
        kwargs = json.loads(form.keyword_arguments.data)
        now = datetime.now()

        data = DatabaseSchedulerEntry(
            name=form.name.data,
            owner_id=form.owner.data.id,
            task=form.task.data,
            interval_id=None,
            crontab_id=sch.id,
            args=args,
            kwargs=kwargs,
            queue=form.queue.data,
            exchange=None,
            routing_key=None,
            expires=form.expires.data,
            enabled=True,
            last_run_at=now,
            total_run_count=0,
            date_changed=now,
        )

        db.session.add(data)
        db.session.commit()

        return redirect(url_for("admin.scheduled_tasks"))

    return render_template_context("admin/edit_scheduled_task.html", form=form, title="Add new crontab task")


@admin.route("/edit_interval_task/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_interval_task(id):
    """
    Edit an existing fixed-interval task
    :return:
    """

    data = DatabaseSchedulerEntry.query.get_or_404(id)
    form = EditIntervalScheduledTask(obj=data)

    if form.validate_on_submit():
        # build or lookup an appropriate IntervalSchedule record from the database
        sch = IntervalSchedule.query.filter_by(every=form.every.data, period=form.period.data).first()

        if sch is None:
            sch = IntervalSchedule(every=form.every.data, period=form.period.data)
            db.session.add(sch)
            db.session.flush()

        args = json.loads(form.arguments.data)
        kwargs = json.loads(form.keyword_arguments.data)

        data.name = form.name.data
        data.owner_id = form.owner.data.id
        data.task = form.task.data
        data.queue = form.queue.data
        data.interval_id = sch.id
        data.crontab_id = None
        data.args = args
        data.kwargs = kwargs
        data.expires = form.expires.data
        data.date_changed = datetime.now()

        db.session.commit()

        return redirect(url_for("admin.scheduled_tasks"))

    else:
        if request.method == "GET":
            form.every.data = data.interval.every
            form.period.data = data.interval.period

    return render_template_context("admin/edit_scheduled_task.html", task=data, form=form, title="Edit fixed-interval task")


@admin.route("/edit_crontab_task/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_crontab_task(id):
    """
    Edit an existing fixed-interval task
    :return:
    """

    data = DatabaseSchedulerEntry.query.get_or_404(id)
    form = EditCrontabScheduledTask(obj=data)

    if form.validate_on_submit():
        # build or lookup an appropriate IntervalSchedule record from the database
        sch = CrontabSchedule.query.filter_by(
            minute=form.minute.data,
            hour=form.hour.data,
            day_of_week=form.day_of_week.data,
            day_of_month=form.day_of_month.data,
            month_of_year=form.month_of_year.data,
        ).first()

        if sch is None:
            sch = CrontabSchedule(
                minute=form.minute.data,
                hour=form.hour.data,
                day_of_week=form.day_of_week.data,
                day_of_month=form.day_of_month.data,
                month_of_year=form.month_of_year.data,
            )
            db.session.add(sch)
            db.session.flush()

        args = json.loads(form.arguments.data)
        kwargs = json.loads(form.keyword_arguments.data)

        data.name = form.name.data
        data.owner_id = form.owner.data.id
        data.task = form.task.data
        data.queue = form.queue.data
        data.interval_id = None
        data.crontab_id = sch.id
        data.args = args
        data.kwargs = kwargs
        data.expires = form.expires.data
        data.date_changed = datetime.now()

        db.session.commit()

        return redirect(url_for("admin.scheduled_tasks"))

    else:
        if request.method == "GET":
            form.minute.data = data.crontab.minute
            form.hour.data = data.crontab.hour
            form.day_of_week.data = data.crontab.day_of_week
            form.day_of_month.data = data.crontab.day_of_month
            form.month_of_year.data = data.crontab.month_of_year

    return render_template_context("admin/edit_scheduled_task.html", task=data, form=form, title="Add new crontab task")


@admin.route("/delete_scheduled_task/<int:id>")
@roles_required("root")
def delete_scheduled_task(id):
    """
    Remove an existing scheduled task
    :return:
    """

    task = DatabaseSchedulerEntry.query.get_or_404(id)

    db.session.delete(task)
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/activate_scheduled_task/<int:id>")
@roles_required("root")
def activate_scheduled_task(id):
    """
    Mark a scheduled task as active
    :return:
    """

    task = DatabaseSchedulerEntry.query.get_or_404(id)

    task.enabled = True
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/deactivate_scheduled_task/<int:id>")
@roles_required("root")
def deactivate_scheduled_task(id):
    """
    Mark a scheduled task as inactive
    :return:
    """

    task = DatabaseSchedulerEntry.query.get_or_404(id)

    task.enabled = False
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/launch_scheduled_task/<int:id>")
@roles_required("root")
def launch_scheduled_task(id):
    """
    Launch a specified task as a background task
    :param id:
    :return:
    """

    record = DatabaseSchedulerEntry.query.get_or_404(id)

    task_id = register_task(record.name, current_user, "Scheduled task launched from web user interface")

    celery = current_app.extensions["celery"]
    tk = celery.tasks[record.task]

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(
        init.si(task_id, record.name),
        tk.signature(record.args, record.kwargs, immutable=True),
        final.si(task_id, record.name, current_user.id, notify=True),
    ).on_error(error.si(task_id, record.name, current_user.id))

    seq.apply_async(task_id=task_id)

    return redirect(redirect_url())


@admin.route("/backups_overview", methods=["GET", "POST"])
@roles_required("root")
def backups_overview():
    """
    Generate the backup overview
    :return:
    """

    form = EditBackupOptionsForm(request.form)

    keep_hourly, keep_daily, lim, backup_max, last_change = get_backup_config()
    limit, units = lim

    backup_count = compute_current_backup_count()
    backup_total_size = compute_current_backup_size()

    if backup_total_size is None:
        size = "(no backups currently held)"
    else:
        size = format_size(backup_total_size)

    if form.validate_on_submit():
        set_backup_config(form.keep_hourly.data, form.keep_daily.data, form.backup_limit.data, form.limit_units.data)
        flash("Your new backup configuration has been saved", "success")

    else:
        if request.method == "GET":
            form.keep_hourly.data = keep_hourly
            form.keep_daily.data = keep_daily
            form.backup_limit.data = limit
            form.limit_units.data = units

    # if there are enough datapoints, generate some plots showing how the backup size is scaling with time
    if backup_count > 1:
        # extract lists of data points
        backup_dates = db.session.query(BackupRecord.date).order_by(BackupRecord.date).all()
        archive_size = db.session.query(BackupRecord.archive_size).order_by(BackupRecord.date).all()
        backup_size = db.session.query(BackupRecord.backup_size).order_by(BackupRecord.date).all()

        MB_SIZE = 1024 * 1024

        dates = [x[0] for x in backup_dates]
        arc_size = [x[0] / MB_SIZE for x in archive_size]
        bk_size = [x[0] / MB_SIZE for x in backup_size]

        archive_plot = figure(
            title="Archive size as a function of time", x_axis_label="Time of backup", x_axis_type="datetime", width=800, height=300
        )
        archive_plot.sizing_mode = "scale_width"
        archive_plot.line(dates, arc_size, legend_label="archive size in Mb", line_color="blue", line_width=2)
        archive_plot.toolbar.logo = None
        archive_plot.border_fill_color = None
        archive_plot.background_fill_color = "lightgrey"
        archive_plot.legend.location = "bottom_right"

        backup_plot = figure(
            title="Total backup size as a function of time", x_axis_label="Time of backup", x_axis_type="datetime", width=800, height=300
        )
        backup_plot.sizing_mode = "scale_width"
        backup_plot.line(dates, bk_size, legend_label="backup size in Mb", line_color="red", line_width=2)
        backup_plot.toolbar.logo = None
        backup_plot.border_fill_color = None
        backup_plot.background_fill_color = "lightgrey"
        backup_plot.legend.location = "bottom_right"

        archive_script, archive_div = components(archive_plot)
        backup_script, backup_div = components(backup_plot)

    else:
        archive_script = None
        archive_div = None
        backup_script = None
        backup_div = None

    # extract data on last few backups
    last_batch = BackupRecord.query.order_by(BackupRecord.date.desc()).limit(4).all()

    if backup_max is not None:
        # construct empty/full gauge
        how_full = float(backup_total_size) / float(backup_max)
        angle = 2 * pi * how_full
        start_angle = pi / 2.0
        end_angle = pi / 2.0 - angle if angle < pi / 2.0 else 5.0 * pi / 2.0 - angle

        gauge = figure(width=150, height=150, toolbar_location=None)
        gauge.sizing_mode = "scale_width"
        gauge.annular_wedge(
            x=0,
            y=0,
            inner_radius=0.75,
            outer_radius=1,
            direction="clock",
            line_color=None,
            start_angle=start_angle,
            end_angle=end_angle,
            fill_color="red",
        )
        gauge.annular_wedge(
            x=0,
            y=0,
            inner_radius=0.75,
            outer_radius=1,
            direction="clock",
            line_color=None,
            start_angle=end_angle,
            end_angle=start_angle,
            fill_color="grey",
        )
        gauge.axis.visible = False
        gauge.xgrid.visible = False
        gauge.ygrid.visible = False
        gauge.border_fill_color = None
        gauge.toolbar.logo = None
        gauge.background_fill_color = None
        gauge.outline_line_color = None
        gauge.toolbar.active_drag = None

        annotation = Label(
            x=0,
            y=0,
            x_units="data",
            y_units="data",
            text="{p:.2g}%".format(p=how_full * 100),
            background_fill_alpha=0.0,
            text_align="center",
            text_baseline="middle",
            text_font_style="bold",
        )
        gauge.add_layout(annotation)

        gauge_script, gauge_div = components(gauge)

    else:
        gauge_script = None
        gauge_div = None

    return render_template_context(
        "admin/backup_dashboard/overview.html",
        pane="overview",
        form=form,
        backup_size=size,
        backup_count=backup_count,
        last_change=last_change,
        archive_script=archive_script,
        archive_div=archive_div,
        backup_script=backup_script,
        backup_div=backup_div,
        last_batch=last_batch,
        gauge_script=gauge_script,
        gauge_div=gauge_div,
    )


@admin.route("/manage_backups", methods=["GET", "POST"])
@roles_required("root")
def manage_backups():
    """
    Generate the backup-management view
    :return:
    """
    type_filter = request.args.get("type_filter")

    if type_filter is None:
        type_filter = session.get("admin_backup_type_filter")

    if type_filter is not None and type_filter not in ["all", "scheduled", "rollover", "golive", "close", "confirm", "batch"]:
        type_filter = "all"

    if type_filter is not None:
        session["admin_backup_type_filter"] = type_filter

    property_filter = request.args.get("property_filter")

    if property_filter is None:
        property_filter = session.get("admin_backup_property_filter")

    if property_filter is not None and property_filter not in ["all", "labels", "lock"]:
        property_filter = "all"

    if property_filter is not None:
        session["admin_backup_property_filter"] = property_filter

    backup_count = compute_current_backup_count()

    form = BackupManageForm(request.form)

    if form.validate_on_submit() and form.delete_age.data is True:
        return redirect(url_for("admin.confirm_delete_backup_cutoff", cutoff=(form.weeks.data)))

    return render_template_context(
        "admin/backup_dashboard/manage.html",
        pane="view",
        backup_count=backup_count,
        form=form,
        type_filter=type_filter,
        property_filter=property_filter,
    )


@admin.route("/manage_backups_ajax", methods=["POST"])
@roles_required("root")
def manage_backups_ajax():
    """
    Ajax data point for backup-management view
    :return:
    """
    type_filter = request.args.get("type_filter")
    property_filter = request.args.get("property_filter")

    base_query = db.session.query(BackupRecord).join(User, User.id == BackupRecord.owner_id)

    if type_filter == "scheduled":
        base_query = base_query.filter(BackupRecord.type == BackupRecord.SCHEDULED_BACKUP)
    elif type_filter == "rollover":
        base_query = base_query.filter(BackupRecord.type == BackupRecord.PROJECT_ROLLOVER_FALLBACK)
    elif type_filter == "golive":
        base_query = base_query.filter(BackupRecord.type == BackupRecord.PROJECT_GOLIVE_FALLBACK)
    elif type_filter == "close":
        base_query = base_query.filter(BackupRecord.type == BackupRecord.PROJECT_CLOSE_FALLBACK)
    elif type_filter == "confirm":
        base_query = base_query.filter(BackupRecord.type == BackupRecord.PROJECT_ISSUE_CONFIRM_FALLBACK)
    elif type_filter == "batch":
        base_query = base_query.filter(BackupRecord.type == BackupRecord.BATCH_IMPORT_FALLBACK)

    if property_filter == "labels":
        base_query = base_query.filter(BackupRecord.labels.any(BackupLabel.id != None))
    elif property_filter == "lock":
        base_query = base_query.filter(BackupRecord.locked)

    date = {"search": func.date_format(BackupRecord.date, "%a %d %b %Y %H:%M:%S"), "order": BackupRecord.date}
    initiated = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "order": [User.last_name, User.first_name],
        "search_collation": "utf8_general_ci",
    }
    type = {"order": BackupRecord.type}
    description = {"search": BackupRecord.description, "order": BackupRecord.description, "search_collation": "utf8_general_ci"}
    key = {"search": BackupRecord.unique_name, "order": BackupRecord.unique_name, "search_collation": "utf8_general_ci"}
    db_size = {"order": BackupRecord.db_size}
    archive_size = {"order": BackupRecord.archive_size}

    columns = {
        "date": date,
        "initiated": initiated,
        "type": type,
        "description": description,
        "key": key,
        "db_size": db_size,
        "archive_size": archive_size,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.site.backups_data)


@admin.route("/manual_backup", methods=["GET", "POST"])
@roles_required("root")
def manual_backup():
    """
    Initiate manual backup
    :return:
    """
    form = ManualBackupForm(request.form)

    if form.validate_on_submit():
        label_list = create_new_backup_labels(form)
        label_ids = [l.id for l in label_list]

        tk_name = f"Manual backup initiated by {current_user.name}"
        tk_description = "Perform a manual backup"
        task_id = register_task(tk_name, owner=current_user, description=tk_description)

        celery = current_app.extensions["celery"]
        backup_task = celery.tasks["app.tasks.backup.backup"]

        init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
        final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
        error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

        unlock_date_str = str(form.unlock_date.data) if form.unlock_date.data is not None else None
        args = (current_user.id, BackupRecord.MANUAL_BACKUP, "backup", form.description.data, form.locked.data, unlock_date_str, label_ids)

        seq = chain(
            init.si(task_id, tk_name),
            backup_task.signature(args, None, immutable=True),
            final.si(task_id, tk_name, current_user.id, notify=True),
        ).on_error(error.si(task_id, tk_name, current_user.id))

        seq.apply_async(task_id=task_id)
        return redirect(url_for("admin.manage_backups"))

    else:
        if request.method == "GET":
            default_unlock_date = date.today() + timedelta(weeks=24)

            form.unlock_date.data = default_unlock_date

    return render_template_context("admin/manual_backup.html", form=form)


@admin.route("/confirm_delete_all_backups")
@roles_required("root")
def confirm_delete_all_backups():
    """
    Show confirmation box to delete all backups
    :return:
    """
    title = "Confirm delete"
    panel_title = "Confirm delete all backups"

    action_url = url_for("admin.delete_all_backups")
    message = "<p>Please confirm that you wish to delete all backups.</p><p>Locked backups are not deleted.</p><p>This action cannot be undone.</p>"
    submit_label = "Delete all"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/delete_all_backups")
@roles_required("root")
def delete_all_backups():
    """
    Delete all backups
    :return:
    """
    # hand off job to asynchronous task backend since potentially long-running on a big database
    celery = current_app.extensions["celery"]
    del_backup = celery.tasks["app.tasks.backup.delete_backup"]

    tk_name = "Manual delete backups"
    tk_description = "Manually delete all backups"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    backups = db.session.query(BackupRecord.id).filter_by(~BackupRecord.locked).all()
    work_group = group(del_backup.si(id[0]) for id in backups)

    seq = chain(init.si(task_id, tk_name), work_group, final.si(task_id, tk_name, current_user.id)).on_error(
        error.si(task_id, tk_name, current_user.id)
    )
    seq.apply_async(task_id=task_id)

    return redirect(url_for("admin.manage_backups"))


@admin.route("/confirm_delete_backup_cutoff/<int:cutoff>")
@roles_required("root")
def confirm_delete_backup_cutoff(cutoff):
    """
    Show confirmation box to delete all backups older than a given cutoff
    :param cutoff:
    :return:
    """
    pl = "s"
    if cutoff == 1:
        pl = ""

    title = "Confirm delete"
    panel_title = "Confirm delete all backups older than {c} week{pl}".format(c=cutoff, pl=pl)

    action_url = url_for("admin.delete_backup_cutoff", cutoff=cutoff)
    message = "<p>Please confirm that you wish to delete all backups older than {c} week{pl}.</p>" "<p>This action cannot be undone.</p>".format(
        c=cutoff, pl=pl
    )
    submit_label = "Delete"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/delete_backup_cutoff/<int:cutoff>")
@roles_required("root")
def delete_backup_cutoff(cutoff):
    """
    Delete all backups older than the given cutoff
    :param cutoff:
    :return:
    """
    pl = "s"
    if cutoff == 1:
        pl = ""

    # hand off job to asynchronous task backend since potentially long-running on a big database
    celery = current_app.extensions["celery"]
    del_backup = celery.tasks["app.tasks.backup.prune_backup_cutoff"]

    tk_name = "Manual delete backups"
    tk_description = "Manually delete backups older than {c} week{pl}".format(c=cutoff, pl=pl)
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    now = datetime.now()
    delta = timedelta(weeks=cutoff)
    limit = now - delta

    backups = db.session.query(BackupRecord.id).all()
    work_group = group(del_backup.si(id[0], limit) for id in backups)

    seq = chain(init.si(task_id, tk_name), work_group, final.si(task_id, tk_name, current_user.id)).on_error(
        error.si(task_id, tk_name, current_user.id)
    )
    seq.apply_async(task_id=task_id)

    return redirect(url_for("admin.manage_backups"))


@admin.route("/confirm_delete_backup/<int:id>")
@roles_required("root")
def confirm_delete_backup(id):
    """
    Show confirmation box to delete a backup
    :return:
    """
    # backup_id is a BackupRecord instance
    backup: BackupRecord = BackupRecord.query.get_or_404(id)

    if backup.locked:
        flash(f'Backup {backup.date.trftime("%a %d %b %Y %H:%M:%S")} cannot be deleted because it is locked.', "info")
        return redirect(redirect_url())

    title = "Confirm delete"
    panel_title = "Confirm delete of backup {d}".format(d=backup.date.strftime("%a %d %b %Y %H:%M:%S"))

    action_url = url_for("admin.delete_backup", id=id)
    message = "<p>Please confirm that you wish to delete the backup {d}.</p>" "<p>This action cannot be undone.</p>".format(
        d=backup.date.strftime("%a %d %b %Y %H:%M:%S")
    )
    submit_label = "Delete"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/delete_backup/<int:id>")
@roles_required("root")
def delete_backup(id):
    # backup_id is a BackupRecord instance
    backup: BackupRecord = BackupRecord.query.get_or_404(id)

    if backup.locked:
        flash(f'Backup {backup.date.trftime("%a %d %b %Y %H:%M:%S")} cannot be deleted because it is locked.', "info")
        return redirect(redirect_url())

    success, msg = remove_backup(id)

    if not success:
        flash(f'Could not delete backup. Backend message = "{msg}". Please contact a system administrator.', "error")

    return redirect(url_for("admin.manage_backups"))


@admin.route("/background_tasks")
@roles_required("root")
def background_tasks():
    """
    List all background tasks
    :return:
    """
    status_filter = request.args.get("status_filter")

    if status_filter is None and session.get("background_task_status_filter"):
        status_filter = session["background_task_status_filter"]

    if status_filter is not None:
        if status_filter not in ["all", "pending", "running", "success", "failure"]:
            status_filter = "all"
        session["background_task_status_filter"] = status_filter

    return render_template_context("admin/background_tasks.html", status_filter=status_filter)


@admin.route("/background_ajax", methods=["POST"])
@roles_required("root")
def background_ajax():
    """
    Ajax data point for background tasks view
    :return:
    """
    status_filter = request.args.get("status_filter")

    base_query = db.session.query(TaskRecord).join(User, User.id == TaskRecord.owner_id)

    if status_filter == "pending":
        base_query = base_query.filter(TaskRecord.status == TaskRecord.PENDING)
    elif status_filter == "running":
        base_query = base_query.filter(TaskRecord.status == TaskRecord.RUNNING)
    elif status_filter == "success":
        base_query = base_query.filter(TaskRecord.status == TaskRecord.SUCCESS)
    elif status_filter == "failure":
        base_query = base_query.filter(or_(TaskRecord.status == TaskRecord.FAILURE, TaskRecord.status == TaskRecord.TERMINATED))

    identifier = {"search": TaskRecord.id, "order": TaskRecord.id}
    name = {"search": TaskRecord.name, "order": TaskRecord.id, "search_collation": "utf8_general_ci"}
    owner = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "order": [User.last_name, User.first_name],
        "search_collation": "utf8_general_ci",
    }
    start_time = {"search": func.date_format(TaskRecord.start_date, "%a %d %b %Y %H:%M:%S"), "order": TaskRecord.start_date}
    status = {"order": TaskRecord.status}
    progress = {"order": TaskRecord.progress}
    message = {"search": TaskRecord.message, "order": TaskRecord.message, "search_collation": "utf8_general_ci"}

    columns = {"id": identifier, "name": name, "owner": owner, "start_at": start_time, "status": status, "progress": progress, "message": message}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.site.background_task_data)


@admin.route("/terminate_background_task/<string:id>")
@roles_required("root")
def terminate_background_task(id):
    record = TaskRecord.query.get_or_404(id)

    if record.status == TaskRecord.SUCCESS or record.status == TaskRecord.FAILURE or record.status == TaskRecord.TERMINATED:
        flash('Could not terminate background task "{name}" because it has finished.'.format(name=record.name), "error")
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    celery.control.revoke(record.id, terminate=True, signal="SIGUSR1")

    try:
        # update progress bar
        progress_update(record.id, TaskRecord.TERMINATED, 100, "Task terminated by user", autocommit=False)

        # remove task from database
        db.session.delete(record)
        db.session.commit()
    except SQLAlchemyError as e:
        flash(
            'Could not terminate task "{name}" due to a database error. ' "Please contact a system administrator.".format(name=record.name), "error"
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@admin.route("/delete_background_task/<string:id>")
@roles_required("root")
def delete_background_task(id):
    record = TaskRecord.query.get_or_404(id)

    if record.status == TaskRecord.PENDING or record.status == TaskRecord.RUNNING:
        flash('Could not delete match "{name}" because it has not terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    try:
        # remove task from database
        db.session.delete(record)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        flash('Could not delete match "{name}" due to a database error. ' "Please contact a system administrator.".format(name=record.name), "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/notifications_ajax")
@limiter.exempt
def notifications_ajax():
    """
    Retrieve all notifications for the current user and take care of keep-alive tasks;
    must exit as quickly as possible
    :return:
    """
    # return empty JSON if not logged in; we don't want this endpoint to require that the user is logged in,
    # otherwise we will end up triggering 'you do not have sufficient privileges to view this resource' errors
    # when the session ends but a webpage is still open
    if not current_user.is_authenticated:
        return jsonify({})

    # get timestamp that client wants messages from, if provided
    since = request.args.get("since", 0, type=int)

    redis = get_redis()
    redis.hset("_pings", str(current_user.id), str((datetime.now().isoformat(), since)))

    # query for all notifications associated with the current user
    notifications = current_user.notifications.filter(Notification.timestamp >= since).order_by(Notification.timestamp.asc()).all()

    data = [{"uuid": n.uuid, "type": n.type, "payload": n.payload, "timestamp": n.timestamp} for n in notifications]

    return jsonify(data)


def _compute_allowed_matching_years(current_year):
    # check which year we are going to offer, and whether any project classes are ready to match
    pre_allowed_years = db.session.query(MatchingAttempt.year).distinct().all()
    allowed_years = {y for y, in pre_allowed_years}

    data = get_ready_to_match_data()
    if data["matching_ready"] and not data["rollover_in_progress"]:
        allowed_years = allowed_years | {current_year}

    return allowed_years, data


@admin.route("/manage_matching", methods=["GET", "POST"])
@roles_required("root")
def manage_matching():
    """
    Create the 'manage matching' dashboard view
    :return:
    """
    current_year = get_current_year()
    requested_year_arg = request.args.get("year", None)
    flag, requested_year = is_integer(requested_year_arg)

    allowed_years, data = _compute_allowed_matching_years(current_year)

    if len(allowed_years) == 0:
        if not data["matching_ready"]:
            flash("Automated matching is not yet available because some project classes are not ready", "error")
            return redirect(redirect_url())

        if data["rollover_in_progress"]:
            flash("Automated matching is not available because a rollover of the academic year is underway", "info"),
            return redirect(redirect_url())

        flash("Automated matching is not available because no years are currently eligible", category="info")
        return redirect(redirect_url())

    SelectMatchingYearForm = SelectMatchingYearFormFactory(allowed_years)
    form = SelectMatchingYearForm(request.form)

    if flag and requested_year is not None and requested_year in allowed_years:
        selected_year = requested_year
    elif hasattr(form, "selector") and form.selector.data is not None and form.selector.data in allowed_years:
        selected_year = form.selector.data
    else:
        selected_year = max(allowed_years)

    if hasattr(form, "selector"):
        form.selector.data = selected_year

    info = get_matching_dashboard_data(selected_year)

    return render_template_context("admin/matching/manage.html", pane="manage", info=info, form=form, year=selected_year)


@admin.route("/matches_ajax")
@roles_required("root")
def matches_ajax():
    """
    Create the 'manage matching' dashboard view
    :return:
    """
    current_year = get_current_year()

    allowed_years, data = _compute_allowed_matching_years(current_year)
    if len(allowed_years) == 0:
        return jsonify({})

    selected_year = request.args.get("year", None)
    if selected_year is None:
        return jsonify({})

    matches = db.session.query(MatchingAttempt).filter_by(year=selected_year).all()

    return ajax.admin.matches_data(matches, is_root=True, text="matching dashboard", url=url_for("admin.manage_matching", year=selected_year))


@admin.route("/skip_matching")
@roles_required("root")
def skip_matching():
    """
    Mark current set of ProjectClassConfig instances to skip automated matching
    :return:
    """
    current_year = get_current_year()

    pcs = db.session.query(ProjectClass).filter_by(active=True).order_by(ProjectClass.name.asc()).all()

    for pclass in pcs:
        # get current configuration record for this project class
        config = pclass.most_recent_config

        if config is not None and config.year == current_year:
            config.skip_matching = True

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Can not skip matching due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/create_match", methods=["GET", "POST"])
@roles_required("root")
def create_match():
    """
    Create the 'create match' dashboard view
    :return:
    """
    current_year = get_current_year()
    selected_year = request.args.get("year", current_year)

    # check that all projects are ready to match
    data = get_ready_to_match_data()

    if selected_year == current_year and data["rollover_in_progress"]:
        flash("Automated matching is not available because a rollover of the academic year is underway", "info"),
        return redirect(redirect_url())

    info = get_matching_dashboard_data(selected_year)

    base_id = request.args.get("base_id", None)

    base_match: MatchingAttempt
    base_match = None
    if base_id is not None:
        base_match = MatchingAttempt.query.get_or_404(base_id)

        if base_match.year != selected_year:
            flash(
                f'Cannot use base match "{base_match.name}" because it belongs to a different '
                f"academic year (base match year = {base_match.year}, selected year = {selected_year}",
                "info",
            )
            return redirect(redirect_url())

    NewMatchForm = NewMatchFormFactory(current_year, base_id=base_id, base_match=base_match)
    form = NewMatchForm(request.form)

    if form.validate_on_submit():
        offline = False

        if form.submit.data:
            task_name = 'Perform project matching for "{name}"'.format(name=form.name.data)
            desc = "Automated project matching task"

        elif form.offline.data:
            offline = True
            task_name = 'Generate file for offline matching for "{name}"'.format(name=form.name.data)
            desc = "Produce .LP file for download and offline matching"

        else:
            raise RuntimeError("Unknown submit button in create_match()")

        uuid = register_task(task_name, owner=current_user, description=desc)

        include_control = getattr(form, "include_only_submitted", None)
        # logic for include_only_submitted is a bit delicate:
        #   Form    Base    Outcome
        #   T/F     None    T/F based on form
        #   T/F     True    T/F based on form
        #   absent  False   False
        include_only_submitted = (include_control.data if include_control is not None else False) and (
            base_match.include_only_submitted if base_match is not None else True
        )

        base_bias_control = getattr(form, "base_bias", None)
        force_base_control = getattr(form, "force_base", None)

        attempt = MatchingAttempt(
            year=selected_year,
            base_id=base_id,
            base_bias=base_bias_control.data if base_bias_control is not None else None,
            force_base=force_base_control.data if force_base_control is not None else None,
            name=form.name.data,
            celery_id=uuid,
            finished=False,
            celery_finished=False,
            awaiting_upload=offline,
            outcome=None,
            published=False,
            selected=False,
            construct_time=None,
            compute_time=None,
            include_only_submitted=include_only_submitted,
            ignore_per_faculty_limits=form.ignore_per_faculty_limits.data,
            ignore_programme_prefs=form.ignore_programme_prefs.data,
            years_memory=form.years_memory.data,
            supervising_limit=form.supervising_limit.data,
            marking_limit=form.marking_limit.data,
            max_marking_multiplicity=form.max_marking_multiplicity.data,
            max_different_group_projects=form.max_different_group_projects.data,
            max_different_all_projects=form.max_different_all_projects.data,
            levelling_bias=form.levelling_bias.data,
            supervising_pressure=form.supervising_pressure.data,
            marking_pressure=form.marking_pressure.data,
            CATS_violation_penalty=form.CATS_violation_penalty.data,
            no_assignment_penalty=form.no_assignment_penalty.data,
            intra_group_tension=form.intra_group_tension.data,
            programme_bias=form.programme_bias.data,
            bookmark_bias=form.bookmark_bias.data,
            use_hints=form.use_hints.data,
            require_to_encourage=form.require_to_encourage.data,
            forbid_to_discourage=form.forbid_to_discourage.data,
            encourage_bias=form.encourage_bias.data,
            discourage_bias=form.discourage_bias.data,
            strong_encourage_bias=form.strong_encourage_bias.data,
            strong_discourage_bias=form.strong_discourage_bias.data,
            solver=form.solver.data,
            creation_timestamp=datetime.now(),
            creator_id=current_user.id,
            last_edit_timestamp=None,
            last_edit_id=None,
            score=None,
            lp_file_id=None,
        )

        # check whether there is any work to do -- is there a current config entry for each
        # attached pclass?
        count = 0
        for pclass in form.pclasses_to_include.data:
            config = pclass.get_config(current_year)

            if config is not None:
                if config not in attempt.config_members:
                    count += 1
                    attempt.config_members.append(config)

        if base_match is not None:
            for config in base_match.config_members:
                if config not in attempt.config_members:
                    count += 1
                    attempt.config_members.append(config)

        if count == 0:
            flash("No project classes were specified for inclusion, so no match was computed.", "error")
            return redirect(url_for("admin.manage_caching"))

        def _validate_included_match(match):
            ok = True

            for config_a in attempt.config_members:
                for config_b in match.config_members:
                    if config_a.id == config_b.id:
                        ok = False
                        flash(
                            'Excluded CATS from existing match "{name}" since it contains project class '
                            '"{pname}" which overlaps with the current match'.format(name=match.name, pname=config_a.name)
                        )
                        break

            return ok

        # for matches we are supposed to take account of when levelling workload, check that there is no overlap
        # with the projects we will include in this match
        for match in form.include_matches.data:
            if match not in attempt.include_matches:
                if _validate_included_match(match):
                    attempt.include_matches.append(match)

        if base_match is not None:
            for match in base_match.include_matches:
                if match not in attempt.include_matches:
                    if _validate_included_match(match):
                        attempt.include_matches.append(match)

        try:
            db.session.add(attempt)
            db.session.commit()

            if offline:
                celery = current_app.extensions["celery"]
                match_task = celery.tasks["app.tasks.matching.offline_match"]

                match_task.apply_async(args=(attempt.id, current_user.id), task_id=uuid)

            else:
                celery = current_app.extensions["celery"]
                match_task = celery.tasks["app.tasks.matching.create_match"]

                match_task.apply_async(args=(attempt.id,), task_id=uuid)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not perform matching due to a database error. Please contact a system administrator", "error")

        return redirect(url_for("admin.manage_matching"))

    else:
        if request.method == "GET":
            form.use_hints.data = True

            if base_match is not None:
                # pre-populate form fields with same parameters used for base match
                form.programme_bias.data = base_match.programme_bias
                form.bookmark_bias.data = base_match.bookmark_bias

                form.use_hints.data = base_match.use_hints
                form.require_to_encourage.data = False
                form.forbid_to_discourage.data = False

                form.supervising_limit.data = base_match.supervising_limit
                form.marking_limit.data = base_match.marking_limit
                form.max_marking_multiplicity.data = base_match.max_marking_multiplicity
                form.max_different_group_projects.data = base_match.max_different_group_projects
                form.max_different_all_projects.data = base_match.max_different_all_projects

                form.levelling_bias.data = base_match.levelling_bias
                form.supervising_pressure.data = base_match.supervising_pressure
                form.marking_pressure.data = base_match.marking_pressure
                form.CATS_violation_penalty.data = base_match.CATS_violation_penalty
                form.no_assignment_penalty.data = base_match.no_assignment_penalty

                form.intra_group_tension.data = base_match.intra_group_tension

                form.encourage_bias.data = base_match.encourage_bias
                form.discourage_bias.data = base_match.discourage_bias
                form.strong_encourage_bias.data = base_match.strong_encourage_bias
                form.strong_discourage_bias.data = base_match.strong_discourage_bias

                form.solver.data = base_match.solver

            else:
                form.solver.data = MatchingAttempt.SOLVER_CBC_CMD

    # estimate equitable CATS loading
    data = estimate_CATS_load()

    return render_template_context("admin/matching/create.html", pane="create", info=info, form=form, data=data, base_match=base_match)


@admin.route("/terminate_match/<int:id>")
@roles_required("root")
def terminate_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if record.finished:
        flash('Can not terminate matching task "{name}" because it has finished.'.format(name=record.name), "error")
        return redirect(redirect_url())

    title = "Terminate match"
    panel_title = "Terminate match <strong>{name}</strong>".format(name=record.name)

    action_url = url_for("admin.perform_terminate_match", id=id, url=request.referrer)
    message = (
        "<p>Please confirm that you wish to terminate the matching job "
        "<strong>{name}</strong>.</p>"
        "<p>This action cannot be undone.</p>".format(name=record.name)
    )
    submit_label = "Terminate job"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/perform_terminate_match/<int:id>")
@roles_required("root")
def perform_terminate_match(id):
    record: MatchingRecord = MatchingAttempt.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.manage_matching")

    if record.finished:
        flash('Can not terminate matching task "{name}" because it has finished.'.format(name=record.name), "error")
        return redirect(url)

    if not record.celery_finished:
        celery = current_app.extensions["celery"]
        celery.control.revoke(record.celery_id, terminate=True, signal="SIGUSR1")

    try:
        if not record.celery_finished:
            progress_update(record.celery_id, TaskRecord.TERMINATED, 100, "Task terminated by user", autocommit=False)

        # delete all MatchingRecords associated with this MatchingAttempt; in fact should not be any, but this
        # is just to be sure
        db.session.query(MatchingRecord).filter_by(matching_id=record.id).delete()

        expire_time = datetime.now() + timedelta(days=1)
        if record.lp_file is not None:
            record.lp_file.expiry = expire_time
            record.lp_file = None

        db.session.delete(record)
        db.session.commit()

    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            'Can not terminate matching task "{name}" due to a database error. ' "Please contact a system administrator.".format(name=record.name),
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@admin.route("/delete_match/<int:id>")
@roles_accepted("faculty", "admin", "root")
def delete_match(id):
    attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(attempt):
        return redirect(redirect_url())

    year = get_current_year()
    if attempt.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle', "info")
        return redirect(redirect_url())

    if not current_user.has_role("root") and current_user.id != attempt.creator_id:
        flash('Match "{name}" cannot be deleted because it belongs to another user')
        return redirect(redirect_url())

    if not attempt.finished:
        flash(
            'Can not delete match "{name}" because it has not terminated. If you wish to delete this '
            "match, please terminate it first.".format(name=attempt.name),
            "error",
        )
        return redirect(redirect_url())

    if attempt.selected:
        flash(
            'Can not delete match "{name}" because it has been selected for use during rollover of the '
            "academic year. Please deselect and unpublish this match before attempting to delete "
            "it.".format(name=attempt.name),
            "error",
        )
        return redirect(redirect_url())

    if attempt.published:
        flash(
            'Can not delete match "{name}" because it has been published to convenors. Please unpublish '
            "this match before attempting to delete it.".format(name=attempt.name),
            "error",
        )
        return redirect(redirect_url())

    title = "Delete match"
    panel_title = "Delete match <strong>{name}</strong>".format(name=attempt.name)

    action_url = url_for("admin.perform_delete_match", id=id, url=request.referrer)
    message = (
        "<p>Please confirm that you wish to delete the matching "
        "<strong>{name}</strong>.</p>"
        "<p>This action cannot be undone.</p>".format(name=attempt.name)
    )
    submit_label = "Delete match"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/perform_delete_match/<int:id>")
@roles_accepted("faculty", "admin", "root")
def perform_delete_match(id):
    attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.manage_matching")

    if not validate_match_inspector(attempt):
        return redirect(url)

    year = get_current_year()
    if attempt.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle', "info")
        return redirect(url)

    if not current_user.has_role("root") and current_user.id != attempt.creator_id:
        flash('Match "{name}" cannot be deleted because it belongs to another user')
        return redirect(url)

    if not attempt.finished:
        flash('Can not delete match "{name}" because it has not terminated.'.format(name=attempt.name), "error")
        return redirect(url)

    if attempt.selected:
        flash(
            'Can not delete match "{name}" because it has been selected for use during rollover of the '
            "academic year. Please deselect and unpublish this match before attempting to delete "
            "it.".format(name=attempt.name),
            "error",
        )
        return redirect(url)

    if attempt.published:
        flash(
            'Can not delete match "{name}" because it has been published to convenors. Please unpublish '
            "this match before attempting to delete it.".format(name=attempt.name),
            "error",
        )
        return redirect(url)

    try:
        expire_time = datetime.now() + timedelta(days=1)
        if attempt.lp_file is not None:
            attempt.lp_file.expiry = expire_time
            attempt.lp_file = None

        db.session.delete(attempt)
        db.session.commit()
        flash('Match "{name}" was successfully deleted.'.format(name=attempt.name), "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        flash('Can not delete match "{name}" due to a database error. ' "Please contact a system administrator.".format(name=attempt.name), "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@admin.route("/clean_up_match/<int:id>")
@roles_accepted("faculty", "admin", "root")
def clean_up_match(id):
    attempt = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(attempt):
        return redirect(redirect_url())

    year = get_current_year()
    if attempt.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle', "info")
        return redirect(redirect_url())

    if not attempt.finished:
        flash('Can not clean up match "{name}" because it has not terminated.'.format(name=attempt.name), "error")
        return redirect(redirect_url())

    title = "Clean up match"
    panel_title = "Clean up match <strong>{name}</strong>".format(name=attempt.name)

    action_url = url_for("admin.perform_clean_up_match", id=id, url=request.referrer)
    message = (
        "<p>Please confirm that you wish to clean up the matching "
        "<strong>{name}</strong>.</p>"
        "<p>Some selectors may be removed if they are no longer available for conversion.</p>"
        "<p>This action cannot be undone.</p>".format(name=attempt.name)
    )
    submit_label = "Clean up match"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/perform_clean_up_match/<int:id>")
@roles_accepted("faculty", "admin", "root")
def perform_clean_up_match(id):
    attempt = MatchingAttempt.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.manage_matching")

    if not validate_match_inspector(attempt):
        return redirect(url)

    year = get_current_year()
    if attempt.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle', "info")
        return redirect(url)

    if not attempt.finished:
        flash('Can not clean up match "{name}" because it has not terminated.'.format(name=attempt.name), "error")
        return redirect(url)

    if not current_user.has_role("root") and current_user.id != attempt.creator_id:
        flash('Match "{name}" cannot be cleaned up because it belongs to another user')
        return redirect(url)

    try:
        # delete all MatchingRecords associated with selectors who are not converting
        for rec in attempt.records:
            if not rec.selector.convert_to_submitter:
                db.session.delete(rec)

        db.session.commit()
        flash('Match "{name}" was successfully cleaned up.'.format(name=attempt.name), "success")
    except SQLAlchemyError as e:
        db.session.rollback()
        flash('Can not clean up match "{name}" due to a database error. ' "Please contact a system administrator.".format(name=attempt.name), "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@admin.route("/revert_match/<int:id>")
@roles_accepted("faculty", "admin", "root")
def revert_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle', "info")
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash('Can not revert match "{name}" because it is still awaiting ' "manual upload.".format(name=record.name), "error")
        else:
            flash('Can not revert match "{name}" because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Can not revert match "{name}" because it did not yield a usable outcome.'.format(name=record.name), "error")
        return redirect(redirect_url())

    title = "Revert match"
    panel_title = "Revert match <strong>{name}</strong>".format(name=record.name)

    action_url = url_for("admin.perform_revert_match", id=id, url=request.referrer)
    message = (
        "<p>Please confirm that you wish to revert the matching "
        "<strong>{name}</strong> to its original state.</p>"
        "<p>This action cannot be undone.</p>".format(name=record.name)
    )
    submit_label = "Revert match"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/perform_revert_match/<int:id>")
@roles_accepted("faculty", "admin", "root")
def perform_revert_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle', "info")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        # TODO consider an alternative implementation here
        url = url_for("admin.manage_matching")

    if not record.finished:
        if record.awaiting_upload:
            flash('Can not revert match "{name}" because it is still awaiting ' "manual upload.".format(name=record.name), "error")
        else:
            flash('Can not revert match "{name}" because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Can not revert match "{name}" because it did not yield a usable outcome.'.format(name=record.name), "error")
        return redirect(redirect_url())

    # hand off revert job to asynchronous queue
    celery = current_app.extensions["celery"]
    revert = celery.tasks["app.tasks.matching.revert"]

    tk_name = "Revert {name}".format(name=record.name)
    tk_description = "Revert matching to its original state"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(init.si(task_id, tk_name), revert.si(record.id), final.si(task_id, tk_name, current_user.id)).on_error(
        error.si(task_id, tk_name, current_user.id)
    )
    seq.apply_async(task_id=task_id)

    return redirect(url)


@admin.route("/duplicate_match/<int:id>")
@roles_accepted("faculty", "admin", "root")
def duplicate_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle.', "info")
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash('Can not duplicate match "{name}" because it is still awaiting ' "manual upload".format(name=record.name), "error")
        else:
            flash('Can not duplicate match "{name}" because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Can not duplicate match "{name}" because it did not yield a usable outcome.'.format(name=record.name), "error")
        return redirect(redirect_url())

    suffix = 2
    while suffix < 100:
        new_name = "{name} #{suffix}".format(name=record.name, suffix=suffix)

        if MatchingAttempt.query.filter_by(name=new_name, year=year).first() is None:
            break

        suffix += 1

    if suffix >= 100:
        flash('Can not duplicate match "{name}" because a new unique tag could not ' "be generated.".format(name=record.name), "error")
        return redirect(redirect_url())

    # hand off duplicate job to asynchronous queue
    celery = current_app.extensions["celery"]
    duplicate = celery.tasks["app.tasks.matching.duplicate"]

    tk_name = "Duplicate {name}".format(name=record.name)
    tk_description = "Duplicate matching"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(init.si(task_id, tk_name), duplicate.si(record.id, new_name, current_user.id), final.si(task_id, tk_name, current_user.id)).on_error(
        error.si(task_id, tk_name, current_user.id)
    )
    seq.apply_async(task_id=task_id)

    return redirect(redirect_url())


@admin.route("/rename_match/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def rename_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle', "info")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.manage_matching")

    RenameMatchForm = RenameMatchFormFactory(year)
    form = RenameMatchForm(request.form)
    form.record = record

    if form.validate_on_submit():
        try:
            record.name = form.name.data
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(
                'Could not rename match "{name}" due to a database error. ' "Please contact a system administrator.".format(name=record.name), "error"
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)

    return render_template_context("admin/match_inspector/rename.html", form=form, record=record, url=url)


@admin.route("/compare_match/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def compare_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash('Can not compare match "{name}" because it is still awaiting ' "manual upload.".format(name=record.name), "error")
        else:
            flash('Can not compare match "{name}" because it has not yet terminated.'.format(name=record.name), "error")

    if not record.solution_usable:
        flash('Can not compare match "{name}" because it did not yield a usable outcome.'.format(name=record.name), "error")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    year = get_current_year()
    our_pclasses = {x.id for x in record.available_pclasses}

    CompareMatchForm = CompareMatchFormFactory(year, record.id, our_pclasses, current_user.has_role("root"))
    form = CompareMatchForm(request.form)

    if form.validate_on_submit():
        comparator = form.target.data
        return redirect(url_for("admin.do_match_compare", id1=id, id2=comparator.id, text=text, url=url))

    return render_template_context("admin/match_inspector/compare_setup.html", form=form, record=record, text=text, url=url)


@admin.route("/do_match_compare/<int:id1>/<int:id2>")
@roles_accepted("faculty", "admin", "root")
def do_match_compare(id1, id2):
    record1 = MatchingAttempt.query.get_or_404(id1)
    record2 = MatchingAttempt.query.get_or_404(id2)

    pclass_filter = request.args.get("pclass_filter")
    diff_filter = request.args.get("diff_filter")
    text = request.args.get("text", None)
    url = request.args.get("url", None)

    if url is None:
        url = redirect_url()

    if not validate_match_inspector(record1) or not validate_match_inspector(record2):
        return redirect(url)

    if not record1.finished:
        if record1.awaiting_upload:
            flash('Can not compare match "{name}" because it is still awaiting ' "manual upload.".format(name=record1.name), "error")
        else:
            flash('Can not compare match "{name}" because it has not yet terminated.'.format(name=record1.name), "error")
        return redirect(url)

    if not record1.solution_usable:
        flash('Can not compare match "{name}" because it did not yield a usable outcome.'.format(name=record1.name), "error")
        return redirect(url)

    if not record2.finished:
        if record2.awaiting_upload:
            flash('Can not compare match "{name}" because it is still awaiting ' "manual upload.".format(name=record2.name), "error")
        else:
            flash('Can not compare match "{name}" because it has not yet terminated.'.format(name=record2.name), "error")
        return redirect(url)

    if not record2.solution_usable:
        flash('Can not compare match "{name}" because it did not yield a usable outcome.'.format(name=record2.name), "error")
        return redirect(url)

    pclasses1 = record1.available_pclasses
    pclasses2 = record2.available_pclasses

    pclass_dict = {}

    for pclass in pclasses1:
        pclass: ProjectClass
        if pclass.id not in pclass_dict:
            pclass_dict[pclass.id] = pclass

    for pclass in pclasses2:
        pclass: ProjectClass
        if pclass.id not in pclass_dict:
            pclass_dict[pclass.id] = pclass

    pclass_values: Iterable[ProjectClass] = pclass_dict.values()
    pclass_values_ids: List[int] = [p.id for p in pclass_values]

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get("admin_match_pclass_filter"):
        pclass_filter = session["admin_match_pclass_filter"]

    flag, pclass_value = is_integer(pclass_filter)
    if flag:
        if pclass_value not in pclass_values_ids:
            pclass_filter = 'all'
    else:
        if pclass_filter is not None and pclass_filter not in ['all']:
            pclass_filter = 'all'

    if pclass_filter is not None:
        session["admin_match_pclass_filter"] = pclass_filter

    # if no difference filter supplied, check if one is stored in ession
    if diff_filter is None and session.get("admin_match_diff_filter"):
        diff_filter = session["admin_match_diff_filter"]

    if diff_filter is not None and diff_filter not in ['all', 'project', 'supervisor', 'marker', 'moderator']:
        diff_filter = 'all'

    if diff_filter is not None:
        session["admin_match_diff_filter"] = diff_filter

    return render_template_context(
        "admin/match_inspector/compare.html",
        record1=record1,
        record2=record2,
        text=text,
        url=url,
        pclasses=pclass_dict.values(),
        pclass_filter=pclass_filter,
        diff_filter=diff_filter,
    )


@admin.route("/do_match_compare_ajax/<int:id1>/<int:id2>")
@roles_accepted("faculty", "admin", "root")
def do_match_compare_ajax(id1, id2):
    attempt1: MatchingAttempt = MatchingAttempt.query.get_or_404(id1)
    attempt2: MatchingAttempt = MatchingAttempt.query.get_or_404(id2)

    if not validate_match_inspector(attempt1) or not validate_match_inspector(attempt2):
        return jsonify({})

    if not attempt1.finished:
        if attempt1.awaiting_upload:
            flash('Can not compare match "{name}" because it is still awaiting upload of an offline solution.'.format(name=attempt1.name), "error")
        else:
            flash('Can not compare match "{name}" because it has not yet terminated.'.format(name=attempt1.name), "error")
        return jsonify({})

    if attempt1.outcome != MatchingAttempt.OUTCOME_OPTIMAL:
        flash('Can not compare match "{name}" because it did not yield a usable outcome.'.format(name=attempt1.name), "error")
        return jsonify({})

    if not attempt2.finished:
        if attempt2.awaiting_upload:
            flash('Can not compare match "{name}" because it is still awaiting upload of an offline solution.'.format(name=attempt2.name), "error")
        else:
            flash('Can not compare match "{name}" because it has not yet terminated.'.format(name=attempt2.name), "error")
        return jsonify({})

    if not attempt2.solution_usable:
        flash('Can not compare match "{name}" because it did not yield a usable outcome.'.format(name=attempt2.name), "error")
        return jsonify({})

    pclass_filter = request.args.get("pclass_filter")
    flag, pclass_value = is_integer(pclass_filter)

    diff_filter = request.args.get("diff_filter")

    discrepant_records = _build_match_changes(attempt1, attempt2, diff_filter, flag, pclass_value)
    return ajax.admin.compare_match_data(discrepant_records, attempt1, attempt2)


def _build_match_changes(attempt1: MatchingAttempt, attempt2: MatchingAttempt, diff_filter: str, filter_pclasses: bool, pclass_id_value: int,
                         include_only_common_records: bool = False):
    # perform a symmetric comparison between the MatchingRecord instances
    # first, we need to build a dictionary of the MatchingRecord instances in each MatchingAttempt, so that we can
    # quickly perform lookups
    # dictionary is indexed by a pair of selector_id, submission_period
    RecordIndexType = Tuple[int, int]
    RecordDictType = Dict[RecordIndexType, MatchingRecord]

    def build_record_dict(attempt: MatchingAttempt) -> RecordDictType:
        # query supplied MatchingAttempt for an ordered list of records, restricting by project class if required
        if filter_pclasses:
            query = (attempt.records
                     .join(SelectingStudent, SelectingStudent.id == MatchingRecord.selector_id)
                     .join(ProjectClassConfig, ProjectClassConfig.id == SelectingStudent.config_id)
                     .filter(ProjectClassConfig.pclass_id == pclass_id_value)
                     )
        else:
            query = attempt.records
        recs: List[MatchingRecord] = query.order_by(MatchingRecord.selector_id.asc(), MatchingRecord.submission_period.asc())

        # convert to a dictionary, indexed by
        rec_dict: RecordDictType = {(rec.selector_id, rec.submission_period): rec for rec in recs}

        return rec_dict

    recs1 = build_record_dict(attempt1)
    recs2 = build_record_dict(attempt2)

    # obtain set of keys for each group of records
    keys1 = recs1.keys()
    keys2 = recs2.keys()

    # find records that are common to both MatchingAttempt instances
    common_keys = keys1 & keys2

    # find records that are only in attempt1 or attempt1
    attempt1_only_keys = keys1 - common_keys
    attempt2_only_keys = keys2 - common_keys

    # discrepant_records will hold the records that differ
    discrepant_records = []

    # iterate over common_keys and check for differences between the MatchingRecord cases
    for key in common_keys:
        key: RecordIndexType
        rec1: MatchingRecord = recs1[key]
        rec2: MatchingRecord = recs2[key]

        if rec1.selector_id != rec2.selector_id:
            raise RuntimeError("do_match_compare_ajax: rec1.selector_id and rec2.selector_id do not match")

        if rec1.submission_period != rec2.submission_period:
            raise RuntimeError("do_match_compare_ajax: rec1.submission_period and rec2.submission_period do not match")

        # dictionary is indexed by user_id
        RoleDictType = Dict[int, MatchingRole]

        def get_role_dict(rec: MatchingRecord, roles: Union[int, List[int]]) -> RoleDictType:
            if not isinstance(roles, list):
                roles = [roles]

            role_records: List[MatchingRole] = rec.roles.filter(MatchingRole.role.in_(roles))
            role_dict: RoleDictType = {role.user_id: role for role in role_records}

            return role_dict

        def get_supervisor_roles(rec: MatchingRecord) -> RoleDictType:
            return get_role_dict(rec, [MatchingRole.ROLE_SUPERVISOR, MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR])

        def get_marker_roles(rec: MatchingRecord) -> RoleDictType:
            return get_role_dict(rec, MatchingRole.ROLE_MARKER)

        def get_moderator_roles(rec: MatchingRecord) -> RoleDictType:
            return get_role_dict(rec, MatchingRole.ROLE_MODERATOR)

        def find_record_changes(rec1: MatchingRecord, rec2: MatchingRecord, diff_filter: str) -> List[str]:
            # is the project assignment different?
            changes = []

            if diff_filter == 'all' or diff_filter == 'project':
                if rec1.project_id != rec2.project_id:
                    changes.append('project')

            # check for differing supervisor roles
            if diff_filter == 'all' or diff_filter == 'supervisor':
                supervisors1: RoleDictType = get_supervisor_roles(rec1)
                supervisors2: RoleDictType = get_supervisor_roles(rec2)
                supervisors_diff = supervisors1.keys() ^ supervisors2.keys()
                if len(supervisors_diff) > 0:
                    changes.append('supervisor')

            # check for differing marker roles
            if diff_filter == 'all' or diff_filter == 'marker':
                markers1: RoleDictType = get_marker_roles(rec1)
                markers2: RoleDictType = get_marker_roles(rec2)
                markers_diff = markers1.keys() ^ markers2.keys()
                if len(markers_diff) > 0:
                    changes.append('marker')

            # check for differing moderator roles
            if diff_filter == 'all' or diff_filter == 'moderator':
                moderators1: RoleDictType = get_moderator_roles(rec1)
                moderators2: RoleDictType = get_moderator_roles(rec2)
                moderators_diff = moderators1.keys() ^ moderators2.keys()
                if len(moderators_diff) > 0:
                    changes.append('moderator')

            return changes

        # test whether there is a disagreement between records
        changes: List[str] = find_record_changes(rec1, rec2, diff_filter)

        # if so, add this record pair to the discrepant pile
        if len(changes) > 0:
            discrepant_records.append((rec1, rec2, changes))

    if not include_only_common_records:
        # iterate over keys that are only in one match or the other
        for key in attempt1_only_keys:
            key: RecordIndexType
            rec: MatchingRecord = recs1[key]

            discrepant_records.append((rec, None, ['all']))
        for key in attempt2_only_keys:
            key: RecordIndexType
            rec: MatchingRecord = recs2[key]

            discrepant_records.append((None, rec, ['all']))

    return discrepant_records


@admin.route("/replace_matching_record/<int:src_id>/<int:dest_id>")
@roles_accepted("faculty", "admin", "root")
def replace_matching_record(src_id, dest_id):
    source: MatchingRecord = MatchingRecord.query.get_or_404(src_id)
    dest: MatchingRecord = MatchingRecord.query.get_or_404(dest_id)

    if not validate_match_inspector(source.matching_attempt) or not validate_match_inspector(dest.matching_attempt):
        return redirect(redirect_url())

    year = get_current_year()
    if dest.matching_attempt.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle', "info")
        return redirect(redirect_url())

    if source.selector_id != dest.selector_id:
        flash("Cannot merge these matching records because they do not refer to the same selector", "error")
        return redirect(redirect_url())

    if source.submission_period != dest.submission_period:
        flash("Cannot merge these matching records because they do not refer to the same submission period", "error")
        return redirect(redirect_url())

    try:
        # overwrite destination project assignment
        dest.project_id = source.project_id

        # overwrite alternative data
        dest.alternative = source.alternative
        dest.parent_id = source.parent_id
        dest.priority = source.priority

        # overwrite rank
        dest.rank = source.rank

        # deep copy role assignments
        dest.roles = []
        for old_role in source.roles:
            old_role: MatchingRole

            new_role = MatchingRole(
                user_id=old_role.user_id,
                role=old_role.role,
            )
            dest.roles.append(new_role)

        dest.matching_attempt.last_edit_id = current_user.id
        dest.matching_attempt.last_edit_timestamp = datetime.now()

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Can not replace matching record due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/insert_matching_record/<int:src_id>/<int:attempt_id>")
@roles_accepted("faculty", "admin", "root")
def insert_matching_record(src_id, attempt_id):
    source_record: MatchingRecord = MatchingRecord.query.get_or_404(src_id)
    dest_attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(attempt_id)

    if not validate_match_inspector(source_record.matching_attempt) or not validate_match_inspector(dest_attempt):
        return redirect(redirect_url())

    year = get_current_year()
    if dest_attempt.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle', "info")
        return redirect(redirect_url())

    sel: SelectingStudent = source_record.selector
    if sel.config not in dest_attempt.config_members:
        flash(
            f'Cannot insert this matching record into attempt "{dest_attempt.name}" because it does not contain matches for projects of type "{sel.config.name}"',
            'error')
        return redirect(redirect_url())

    try:
        # insert new MatchingRecord instance
        new_record = MatchingRecord(
            matching_id=dest_attempt.id,
            selector_id=source_record.selector_id,
            submission_period=source_record.submission_period,
            project_id=source_record.project_id,
            original_project_id=source_record.project_id,
            rank=source_record.rank,
            alternative=source_record.alternative,
            parent_id=source_record.parent_id,
            priority=source_record.priority,
        )
        db.session.add(new_record)
        db.session.flush()

        # deep copy role assignments
        new_record.roles = []
        new_record.original_roles = []
        for old_role in source_record.roles:
            old_role: MatchingRole

            new_role = MatchingRole(
                user_id=old_role.user_id,
                role=old_role.role,
            )
            new_record.roles.append(new_role)

            new_original_role = MatchingRole(
                user_id=old_role.user_id,
                role=old_role.role,
            )
            new_record.original_roles.append(new_original_role)

        dest_attempt.last_edit_id = current_user.id
        dest_attempt.last_edit_timestamp = datetime.now()

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Can not insert matching record due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/match_export_excel/<int:matching_id>")
@roles_accepted("faculty", "admin", "root")
def match_export_excel(matching_id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(matching_id)

    if not record.finished:
        if record.awaiting_upload:
            flash('Match "{name}" is not yet available for export because it is still awaiting manual upload.'.format(name=record.name), "error")
        else:
            flash('Match "{name}" is not yet available for export because it has not yet completed.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Match "{name}" is not available for export because it did not yield a useable solution'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    task_id = register_task(
        f'Export matching attempt "{record.name}" to Excel',
        owner=current_user,
        description=f'Export matching attempt "{record.name}" to Excel and send by email',
    )

    celery = current_app.extensions["celery"]
    task = celery.tasks["app.tasks.matching.send_excel_report_by_email"]

    task.apply_async(args=(matching_id, current_user.id, task_id), task_id=task_id)
    flash(f'An Excel report for "{record.name}" is being generated. It will be delivered by email when it is available.')

    return redirect(redirect_url())


@admin.route("/match_student_view/<int:id>")
@roles_accepted("faculty", "admin", "root")
def match_student_view(id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not record.finished:
        if record.awaiting_upload:
            flash('Match "{name}" is not yet available for inspection because it is still awaiting manual upload.'.format(name=record.name), "error")
        else:
            flash('Match "{name}" is not yet available for inspection because it has not yet completed.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Match "{name}" is not available for inspection because it did not yield a useable solution'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    pclass_filter = request.args.get("pclass_filter", default=None)
    type_filter = request.args.get("type_filter", default=None)
    hint_filter = request.args.get("hint_filter", default=None)

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get("admin_match_pclass_filter"):
        pclass_filter = session["admin_match_pclass_filter"]

    if pclass_filter is not None:
        session["admin_match_pclass_filter"] = pclass_filter

    if type_filter is None and session.get("admin_match_type_filter"):
        type_filter = session["admin_match_type_filter"]

    if type_filter not in ["all", "ordinary", "generic"]:
        type_filter = "all"

    if type_filter is not None:
        session["admin_match_type_filter"] = type_filter

    if hint_filter is None and session.get("admin_match_hint_filter"):
        type_filter = session["admin_match_hint_filter"]

    if hint_filter not in ["all", "satisfied", "violated"]:
        hint_filter = "all"

    if hint_filter is not None:
        session["admin_match_hint_filter"] = hint_filter

    pclasses = record.available_pclasses

    return render_template_context(
        "admin/match_inspector/student.html",
        pane="student",
        record=record,
        pclasses=pclasses,
        pclass_filter=pclass_filter,
        type_filter=type_filter,
        hint_filter=hint_filter,
        text=text,
        url=url,
    )


@admin.route("/match_faculty_view/<int:id>")
@roles_accepted("faculty", "admin", "root")
def match_faculty_view(id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not record.finished:
        if record.awaiting_upload:
            flash('Match "{name}" is not yet available for inspection because it is still awaiting manual upload.'.format(name=record.name), "error")
        else:
            flash('Match "{name}" is not yet available for inspection because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Match "{name}" is not available for inspection because it did not yield an optimal solution.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    pclass_filter = request.args.get("pclass_filter", default=None)
    type_filter = request.args.get("type_filter", default=None)
    hint_filter = request.args.get("hint_filter", default=None)
    show_includes = request.args.get("show_includes", default=None)

    if show_includes is not None and show_includes not in ["true", "false"]:
        show_includes = "false"

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get("admin_match_pclass_filter"):
        pclass_filter = session["admin_match_pclass_filter"]

    if pclass_filter is not None:
        session["admin_match_pclass_filter"] = pclass_filter

    if type_filter is None and session.get("admin_match_type_filter"):
        type_filter = session["admin_match_type_filter"]

    if type_filter not in ["all", "ordinary", "generic"]:
        type_filter = "all"

    if type_filter is not None:
        session["admin_match_type_filter"] = type_filter

    if hint_filter is None and session.get("admin_match_hint_filter"):
        type_filter = session["admin_match_hint_filter"]

    if hint_filter not in ["all", "satisfied", "violated"]:
        hint_filter = "all"

    if hint_filter is not None:
        session["admin_match_hint_filter"] = hint_filter

    if show_includes is None and session.get("admin_match_include_match_CATS"):
        show_includes = session["admin_match_include_match_CATS"]

    if show_includes is not None:
        session["admin_match_include_match_CATS"] = show_includes

    pclasses = get_automatch_pclasses()

    return render_template_context(
        "admin/match_inspector/faculty.html",
        pane="faculty",
        record=record,
        pclasses=pclasses,
        pclass_filter=pclass_filter,
        type_filter=type_filter,
        hint_filter=hint_filter,
        show_includes=show_includes,
        text=text,
        url=url,
    )


@admin.route("/match_dists_view/<int:id>")
@roles_accepted("faculty", "admin", "root")
def match_dists_view(id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for inspection because it is still awaiting ' "manual upload.".format(name=record.name), "error"
            )
        else:
            flash('Match "{name}" is not yet available for inspection because it has not yet ' "terminated.".format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Match "{name}" is not available for inspection ' "because it did not yield an optimal solution.".format(name=record.name), "error")
        return redirect(redirect_url())

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    pclass_filter = request.args.get("pclass_filter")

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get("admin_match_pclass_filter"):
        pclass_filter = session["admin_match_pclass_filter"]

    if pclass_filter is not None:
        session["admin_match_pclass_filter"] = pclass_filter

    flag, pclass_value = is_integer(pclass_filter)

    pclasses = get_automatch_pclasses()

    fsum = lambda x: x[0] + x[1] + x[2]
    query = record.faculty_list_query()
    CATS_tot = [fsum(record.get_faculty_CATS(f.id, pclass_value if flag else None)) for f in query.all()]

    CATS_plot = figure(title="Workload distribution", x_axis_label="CATS", width=800, height=300)
    CATS_hist, CATS_edges = histogram(CATS_tot, bins="auto")
    CATS_plot.quad(top=CATS_hist, bottom=0, left=CATS_edges[:-1], right=CATS_edges[1:], fill_color="#036564", line_color="#033649")
    CATS_plot.sizing_mode = "scale_width"
    CATS_plot.toolbar.logo = None
    CATS_plot.border_fill_color = None
    CATS_plot.background_fill_color = "lightgrey"

    CATS_script, CATS_div = components(CATS_plot)

    selectors = record.selector_list_query().all()

    def _get_deltas(s: SelectingStudent):
        if flag:
            if s.config.pclass_id != pclass_value:
                return None

        records: List[MatchingRecord] = s.matching_records.filter(MatchingRecord.matching_id == record.id).all()

        deltas = [r.delta for r in records]
        return sum(deltas) if None not in deltas else None

    delta_set = [_get_deltas(s) for s in selectors]
    delta_set = [x for x in delta_set if x is not None]

    delta_plot = figure(title="Delta distribution", x_axis_label="Total delta", width=800, height=300)
    delta_hist, delta_edges = histogram(delta_set, bins="auto")
    delta_plot.quad(top=delta_hist, bottom=0, left=delta_edges[:-1], right=delta_edges[1:], fill_color="#036564", line_color="#033649")
    delta_plot.sizing_mode = "scale_width"
    delta_plot.toolbar.logo = None
    delta_plot.border_fill_color = None
    delta_plot.background_fill_color = "lightgrey"

    delta_script, delta_div = components(delta_plot)

    return render_template_context(
        "admin/match_inspector/dists.html",
        pane="dists",
        record=record,
        pclasses=pclasses,
        pclass_filter=pclass_filter,
        CATS_script=CATS_script,
        CATS_div=CATS_div,
        delta_script=delta_script,
        delta_div=delta_div,
        text=text,
        url=url,
    )


@admin.route("/match_student_view_ajax/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def match_student_view_ajax(id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return jsonify({})

    if not record.finished or not record.solution_usable:
        return jsonify({})

    pclass_filter = request.args.get("pclass_filter", default=None)
    pclass_flag, pclass_value = is_integer(pclass_filter)

    type_filter = request.args.get("type_filter", default=None)
    hint_filter = request.args.get("hint_filter", default=None)

    url = request.args.get("url", default=None)
    text = request.args.get("text", default=None)

    base_query = record.selector_list_query()

    def search_name(row: SelectingStudent):
        user: User = row.student.user
        return user.name

    def sort_name(row: SelectingStudent):
        user: User = row.student.user
        return [user.last_name, user.first_name]

    def search_pclass(row: SelectingStudent):
        config: ProjectClassConfig = row.config
        return config.name

    def sort_pclass(row: SelectingStudent):
        config: ProjectClassConfig = row.config
        return config.name

    def search_projects(row: SelectingStudent):
        records: List[MatchingRecord] = row.matching_records.filter(MatchingRecord.matching_id == record.id).all()

        def _get_data(rec: MatchingRecord):
            yield rec.project.name if rec.project is not None else ""
            for item in rec.roles:
                item: MatchingRole
                yield item.user.name if item.user is not None else ""

        return list(itertools_chain.from_iterable(_get_data(rec) for rec in records))

    def sort_projects(row: SelectingStudent):
        records: List[MatchingRecord] = (
            row.matching_records.filter(MatchingRecord.matching_id == record.id).order_by(MatchingRecord.submission_period).all()
        )

        return list(rec.project.name if rec.project is not None else "" for rec in records)

    def sort_rank(row: SelectingStudent):
        records: List[MatchingRecord] = row.matching_records.filter(MatchingRecord.matching_id == record.id).all()

        return sum(rec.total_rank for rec in records)

    def sort_score(row: SelectingStudent):
        records: List[MatchingRecord] = row.matching_records.filter(MatchingRecord.matching_id == record.id).all()

        return sum(rec.current_score for rec in records)

    student = {"search": search_name, "order": sort_name}
    pclass = {"search": search_pclass, "order": sort_pclass}
    projects = {"search": search_projects, "order": sort_projects}
    rank = {"order": sort_rank}
    score = {"order": sort_score}
    columns = {"student": student, "pclass": pclass, "projects": projects, "rank": rank, "scores": score}

    filter_list = []

    if pclass_flag:

        def filt(pclass_value, rs: List[MatchingRecord]):
            return any(r.selector.config.pclass_id == pclass_value for r in rs)

        filter_list.append(partial(filt, pclass_value))

    if type_filter == "ordinary":

        def filt(rs: List[MatchingRecord]):
            return any(not r.project.generic for r in rs)

        filter_list.append(filt)

    elif type_filter == "generic":

        def filt(rs: List[MatchingRecord]):
            return any(r.project.generic for r in rs)

        filter_list.append(filt)

    if hint_filter == "satisfied":

        def filt(rs: List[MatchingRecord]):
            return any(len(r.hint_status[0]) > 0 for r in rs)

        filter_list.append(filt)

    elif hint_filter == "violated":

        def filt(rs: List[MatchingRecord]):
            return any(len(r.hint_status[1]) > 0 for r in rs)

        filter_list.append(filt)

    def row_filter(row: SelectingStudent):
        records: List[MatchingRecord] = row.matching_records.filter(MatchingRecord.matching_id == record.id).all()

        return all(f(records) for f in filter_list)

    with ServerSideInMemoryHandler(request, base_query, columns, row_filter=row_filter if len(filter_list) > 0 else None) as handler:

        def row_formatter(selectors: List[SelectingStudent]):
            def _internal_format(ss: List[SelectingStudent]):
                for s in ss:
                    records: List[MatchingRecord] = (
                        s.matching_records.filter(MatchingRecord.matching_id == record.id).order_by(MatchingRecord.submission_period).all()
                    )

                    deltas = [r.delta for r in records]
                    delta = sum(deltas) if None not in deltas else None

                    scores = [r.current_score for r in records]
                    score = sum(scores)

                    yield (records, delta, score)

            return ajax.admin.student_view_data(_internal_format(selectors), record.id, url=url, text=text)

        return handler.build_payload(row_formatter)


@admin.route("/match_faculty_view_ajax/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def match_faculty_view_ajax(id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return jsonify({})

    if not record.finished or not record.solution_usable:
        return jsonify({})

    pclass_filter = request.args.get("pclass_filter", default=None)
    pclass_flag, pclass_value = is_integer(pclass_filter)

    type_filter = request.args.get("type_filter", default=None)
    hint_filter = request.args.get("hint_filter", default=None)
    show_includes = request.args.get("show_includes", default=None)

    base_query = record.faculty_list_query()

    def search_name(row: FacultyData):
        user: User = row.user
        return user.name

    def sort_name(row: FacultyData):
        user: User = row.user
        return [user.last_name, user.first_name]

    def search_projects(row: FacultyData):
        records: List[MatchingRecord] = record.get_supervisor_records(row.id).all()

        return [r.project.name if r.project is not None else "" for r in records]

    def sort_projects(row: FacultyData):
        return get_count(record.get_supervisor_records(row.id))

    def search_marker(row: FacultyData):
        records: List[MatchingRecord] = record.get_marker_records(row.id).all()

        return [r.project.name if r.project is not None else "" for r in records]

    def sort_marker(row: FacultyData):
        return get_count(record.get_marker_records(row.id))

    def sort_workload(row: FacultyData):
        sup, mark, mod = record.get_faculty_CATS(row, pclass_id=pclass_value)

        return sup + mark + mod

    name = {"search": search_name, "order": sort_name}
    projects = {"search": search_projects, "order": sort_projects}
    marking = {"search": search_marker, "order": sort_marker}
    workload = {"order": sort_workload}
    columns = {"name": name, "projects": projects, "marking": marking, "workload": workload}

    filter_list = []

    if pclass_flag:

        def filt(pclass_value, rs: List[MatchingRecord]):
            return any(r.selector.config.pclass_id == pclass_value for r in rs)

        filter_list.append(partial(filt, pclass_value))

    if type_filter == "ordinary":

        def filt(rs: List[MatchingRecord]):
            return any(not r.project.generic for r in rs)

        filter_list.append(filt)

    elif type_filter == "generic":

        def filt(rs: List[MatchingRecord]):
            return any(r.project.generic for r in rs)

        filter_list.append(filt)

    if hint_filter == "satisfied":

        def filt(rs: List[MatchingRecord]):
            return any(len(r.hint_status[0]) > 0 for r in rs)

        filter_list.append(filt)

    elif hint_filter == "violated":

        def filt(rs: List[MatchingRecord]):
            return any(len(r.hint_status[1]) > 0 for r in rs)

        filter_list.append(filt)

    def row_filter(row: FacultyData):
        records: List[MatchingRecord] = record.get_supervisor_records(row.id).all()

        return all(f(records) for f in filter_list)

    with ServerSideInMemoryHandler(request, base_query, columns, row_filter=row_filter if len(filter_list) > 0 else None) as handler:

        def row_formatter(records: List[FacultyData]):
            return ajax.admin.faculty_view_data(
                records, record, pclass_value if pclass_flag else None, type_filter, hint_filter, show_includes == "true"
            )

        return handler.build_payload(row_formatter)


@admin.route("/delete_match_record/<int:attempt_id>/<int:selector_id>")
@roles_accepted("faculty", "admin", "root")
def delete_match_record(attempt_id, selector_id):
    attempt: MatchingAttempt = MatchingAttempt.query.get_or_404(attempt_id)

    if not validate_match_inspector(attempt):
        return redirect(redirect_url())

    if attempt.selected:
        flash(
            'Match "{name}" cannot be edited because an administrative user has marked it as '
            '"selected" for use during rollover of the academic year.'.format(name=attempt.name),
            "info",
        )
        return redirect(redirect_url())

    year = get_current_year()
    if attempt.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=attempt.name), "info")
        return redirect(redirect_url())

    try:
        # remove all matching records associated with this selector
        records = db.session.query(MatchingRecord).filter_by(matching_id=attempt.id, selector_id=selector_id)
        for record in records:
            records: MatchingRecord
            db.session.delete(record)

        db.session.commit()

    except SQLAlchemyError as e:
        flash("Could not delete matching records for this selector because a database error was encountered.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@admin.route("/reassign_match_project/<int:id>/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def reassign_match_project(id, pid):
    record: MatchingRecord = MatchingRecord.query.get_or_404(id)

    if not validate_match_inspector(record.matching_attempt):
        return redirect(redirect_url())

    if record.matching_attempt.selected:
        flash(
            'Match "{name}" cannot be edited because an administrative user has marked it as '
            '"selected" for use during rollover of the academic year.'.format(name=record.matching_attempt.name),
            "info",
        )
        return redirect(redirect_url())

    year = get_current_year()
    if record.matching_attempt.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name), "info")
        return redirect(redirect_url())

    project: LiveProject = LiveProject.query.get_or_404(pid)

    if record.selector.has_submitted:
        submitted_data = record.selector.is_project_submitted(project)
        if submitted_data.get("submitted"):
            adjust = False

            if project.generic:
                # don't change supervisors here
                adjust = True

            else:
                if project.owner is not None:
                    enroll_record = project.owner.get_enrollment_record(project.config.pclass_id)

                    if enroll_record is not None and enroll_record.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED:
                        adjust = True

                        # remove any previous supervision roles and replace with a supervision role for the new project
                        existing_supv = record.roles.filter(
                            MatchingRole.role.in_([MatchingRole.ROLE_SUPERVISOR, MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR])
                        ).all()
                        for item in existing_supv:
                            record.roles.remove(item)

                        new_supv = MatchingRole(user_id=project.owner_id, role=MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR)
                        record.roles.add(new_supv)

                    else:
                        flash(
                            "Could not reassign '{proj}' to {name} because this project's supervisor is no longer "
                            "enrolled for this project class.".format(proj=project.name, name=record.selector.student.user.name)
                        )

            if adjust:
                record.project_id = project.id
                record.rank = record.selector.project_rank(project.id)

                record.matching_attempt.last_edit_id = current_user.id
                record.matching_attempt.last_edit_timestamp = datetime.now()

                try:
                    db.session.commit()
                except SQLAlchemyError as e:
                    flash("Could not reassign matched project because a database error was encountered.", "error")
                    db.session.rollback()
                    current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        else:
            flash(
                "Could not reassign '{proj}' to {name} because this project "
                "was not included in this selector's choices".format(proj=project.name, name=record.selector.student.user.name),
                "error",
            )

    return redirect(redirect_url())


@admin.route("/reassign_match_marker/<int:id>/<int:mid>")
@roles_accepted("faculty", "admin", "root")
def reassign_match_marker(id, mid):
    record: MatchingRecord = MatchingRecord.query.get_or_404(id)

    if not validate_match_inspector(record.matching_attempt):
        return redirect(redirect_url())

    if record.matching_attempt.selected:
        flash(
            'Match "{name}" cannot be edited because an administrative user has marked it as '
            '"selected" for use during rollover of the academic year.'.format(name=record.matching_attempt.name),
            "info",
        )
        return redirect(redirect_url())

    year = get_current_year()
    if record.matching_attempt.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name), "info")
        return redirect(redirect_url())

    # check intended mid is in list of attached second markers
    count = get_count(record.project.assessor_list_query.filter(FacultyData.id == mid))

    if count == 0:
        marker = FacultyData.query.get_or_404(mid)
        flash(
            "Could not assign {name} as marker since "
            'not tagged as available for assigned project "{proj}"'.format(name=marker.user.name, proj=record.project.name),
            "error",
        )

    elif count == 1:
        record.marker_id = mid

        record.matching_attempt.last_edit_id = current_user.id
        record.matching_attempt.last_edit_timestamp = datetime.now()

        db.session.commit()

    else:
        flash("Inconsistent marker counts for matching record (id={id}). Please contact a system administrator".format(id=record.id), "error")

    return redirect(redirect_url())


@admin.route("/reassign_supervisor_roles/<int:rec_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def reassign_supervisor_roles(rec_id):
    record: MatchingRecord = MatchingRecord.query.get_or_404(rec_id)

    if not validate_match_inspector(record.matching_attempt):
        return redirect(redirect_url())

    if record.matching_attempt.selected:
        flash(
            'Match "{name}" cannot be edited because an administrative user has marked it as '
            '"selected" for use during rollover of the academic year.'.format(name=record.matching_attempt.name),
            "info",
        )
        return redirect(redirect_url())

    year = get_current_year()
    if record.matching_attempt.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name), "info")
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    assign_form: EditSupervisorRolesForm = EditSupervisorRolesForm(obj=record)

    if assign_form.validate_on_submit():
        new_supv_roles = assign_form.supervisors.data

        existing_roles = []

        for item in record.roles:
            item: MatchingRole

            if item.role in [MatchingRole.ROLE_SUPERVISOR, MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR]:
                if not any(fd.id == item.user_id for fd in new_supv_roles):
                    record.roles.remove(item)
                else:
                    existing_roles.append(item.user_id)

        for fd in new_supv_roles:
            if fd.id not in existing_roles:
                new_item = MatchingRole(role=MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR, user_id=fd.id)
                record.roles.add(new_item)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash("Could not reassign supervisors for this matching record because a database error was encountered.", "error")
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)

    else:
        if request.method == "GET":
            supv_roles = [
                x.user.faculty_data for x in record.roles if x.role in [MatchingRole.ROLE_SUPERVISOR, MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR]
            ]
            assign_form.supervisors.data = supv_roles

    return render_template_context("admin/match_inspector/reassign_supervisor.html", form=assign_form, record=record, url=url, text=text)


@admin.route("/publish_matching_selectors/<int:id>")
@roles_required("root")
def publish_matching_selectors(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash('Match "{name}" is not yet available for email because it is still awaiting ' "manual upload.".format(name=record.name), "error")
        else:
            flash('Match "{name}" is not yet available for email because it has not yet ' "terminated.".format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be shared by email.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    if not record.published:
        flash(
            'Match "{name}" cannot be advertised to selectors because it has not yet been '
            "published to the module convenor. Please publish the match before attempting to distribute "
            "notifications.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    task_id = register_task(
        "Send matching to selectors", owner=current_user, description='Email details of match "{name}" to submitters'.format(name=record.name)
    )

    celery = current_app.extensions["celery"]
    task = celery.tasks["app.tasks.matching_emails.publish_to_selectors"]

    task.apply_async(args=(id, current_user.id, task_id), task_id=task_id)

    return redirect(redirect_url())


@admin.route("/publish_matching_supervisors/<int:id>")
@roles_required("root")
def publish_matching_supervisors(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash('Match "{name}" is not yet available for email because it is still awaiting ' "manual upload.".format(name=record.name), "error")
        else:
            flash('Match "{name}" is not yet available for email because it has not yet ' "terminated.".format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be shared by email.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    if not record.published:
        flash(
            'Match "{name}" cannot be advertised to supervisors because it has not yet been '
            "published to the module convenor. Please publish the match before attempting to distribute "
            "notifications.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    task_id = register_task(
        "Send matching to supervisors", owner=current_user, description='Email details of match "{name}" to supervisors'.format(name=record.name)
    )

    celery = current_app.extensions["celery"]
    task = celery.tasks["app.tasks.matching_emails.publish_to_supervisors"]

    task.apply_async(args=(id, current_user.id, task_id), task_id=task_id)

    return redirect(redirect_url())


@admin.route("/publish_match/<int:id>")
@roles_required("root")
def publish_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for publication because it is still awaiting ' "manual upload.".format(name=record.name), "error"
            )
        else:
            flash('Match "{name}" is not yet available for publication because it has not yet ' "terminated.".format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution and is not available for use during rollover. '
            "It cannot be shared with convenors.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    record.published = True
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/unpublish_match/<int:id>")
@roles_required("root")
def unpublish_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for unpublication because it is still awaiting ' "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash('Match "{name}" is not yet available for unpublication because it has not yet ' "terminated.".format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Match "{name}" did not yield an optimal solution and is not available for use during rollover. '
            "It cannot be shared with convenors.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    record.published = False
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/select_match/<int:id>")
@roles_required("root")
def select_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    force = request.args.get("force", False)
    if not isinstance(force, bool):
        force = bool(int(force))

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for selection because it is still awaiting ' "manual upload.".format(name=record.name), "error"
            )
        else:
            flash('Match "{name}" is not yet available for selection because it has not yet ' "terminated.".format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Match "{name}" did not yield an optimal solution ' "and is not available for use.".format(name=record.name), "info")
        return redirect(redirect_url())

    if not record.is_valid and not force:
        title = 'Select match "{name}"'.format(name=record.name)
        panel_title = 'Select match "{name}"'.format(name=record.name)

        action_url = url_for("admin.select_match", id=id, force=1, url=url)
        message = (
            '<p>Match "{name}" has validation errors.</p>'
            "<p>Please confirm that you wish to select it for use during rollover of the "
            "academic year.</p>".format(name=record.name)
        )
        submit_label = "Force selection"

        return render_template_context(
            "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
        )

    # determine whether any already-selected projects have allocations for a pclass we own
    our_pclasses = set()
    for item in record.available_pclasses:
        our_pclasses.add(item.id)

    selected_pclasses = set()
    selected = db.session.query(MatchingAttempt).filter_by(year=year, selected=True).all()
    for match in selected:
        for item in match.available_pclasses:
            selected_pclasses.add(item.id)

    intersection = our_pclasses & selected_pclasses
    if len(intersection) > 0:
        flash(
            'Cannot select match "{name}" because some project classes it handles are already '
            "determined by selected matches.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    record.selected = True
    db.session.commit()

    return redirect(url)


@admin.route("/deselect_match/<int:id>")
@roles_required("root")
def deselect_match(id):
    record = MatchingAttempt.query.get_or_404(id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" can no longer be modified because it belongs to a previous selection cycle'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Match "{name}" is not yet available for deselection because it is still awaiting ' "manual upload.".format(name=record.name), "error"
            )
        else:
            flash('Match "{name}" is not yet available for deselection because it has not yet ' "terminated.".format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Match "{name}" did not yield an optimal solution ' "and is not available for use.".format(name=record.name), "info")
        return redirect(redirect_url())

    record.selected = False
    db.session.commit()

    return redirect(redirect_url())


def _validate_match_populate_submitters(record: MatchingAttempt, config: ProjectClassConfig):
    year = get_current_year()
    if record.year != year:
        flash('Match "{name}" cannot be used to populate submitter records because it belongs to a previous selection cycle'.format(name=record.name),
              "info")
        return False

    if config.year != record.year:
        flash(
            'Match "{match_name}" cannot be used to populate submitter records for project type "{pcl_name}", '
            "year = {config_year} because this configuration belongs to a previous "
            "year".format(match_name=record.name, pcl_name=config.name, config_year=config.year)
        )
        return False

    if config.select_in_previous_cycle:
        flash(
            'Match "{match_name}" cannot be used to populate submitter records for project type "{pcl_name}" '
            "because this project type is not configured to use selection in the same cycle as "
            "submission".format(match_name=record.name, pcl_name=config.name)
        )
        return False

    if not record.finished:
        if record.awaiting_upload:
            flash('Match "{name}" is not yet available for use because it is still awaiting ' "manual upload.".format(name=record.name), "error")
        else:
            flash('Match "{name}" is not yet available for use because it has not yet ' "terminated.".format(name=record.name), "error")
        return False

    if not record.solution_usable:
        flash('Match "{name}" did not yield an optimal solution ' "and is not available for use.".format(name=record.name), "info")
        return False

    if not record.published:
        flash(
            'Match "{name}" cannot be used to populate submitter records because it has not yet been '
            "published to the module convenor. Please publish the match before attempting to generate "
            "selectors.".format(name=record.name),
            "info",
        )
        return False

    return True


@admin.route("/populate_submitters_from_match/<int:match_id>/<int:config_id>")
@roles_accepted("faculty", "admin", "root")
def populate_submitters_from_match(match_id, config_id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(match_id)
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(config_id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    if not _validate_match_populate_submitters(record, config):
        return redirect(redirect_url())

    title = "Populate submitters from match"
    panel_title = 'Populate submitters for "{name}" from match ' '"{match_name}"'.format(name=config.name, match_name=record.name)

    action_url = url_for("admin.do_populate_submitters_from_match", match_id=record.id, config_id=config.id, url=redirect_url())
    message = (
        "<p>Please confirm that you wish to populate submitters for <strong>{name}</strong> from match "
        "<strong>{match_name}</strong>.</p>"
        "<p>Changes made during this process cannot be undone.</p>"
        "<p>Project assignments for submitters that already exist will not be modified. "
        "New submitters will be generated if required, "
        "and project assignments will be generated from any submission periods in which they are "
        "missing.</p>".format(name=config.name, match_name=record.name)
    )
    submit_label = "Populate submitters"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/do_populate_submitters_from_match/<int:match_id>/<int:config_id>")
@roles_accepted("faculty", "admin", "root")
def do_populate_submitters_from_match(match_id, config_id):
    record: MatchingAttempt = MatchingAttempt.query.get_or_404(match_id)
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(config_id)

    if not validate_match_inspector(record):
        return redirect(redirect_url())

    if not _validate_match_populate_submitters(record, config):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = home_dashboard_url()

    task_id = register_task(
        "Populate submitters from match",
        owner=current_user,
        description=f'Use match "{record.name}" to populate submitter records in the current cycle for project type "{config.name}"',
    )

    celery = current_app.extensions["celery"]
    task = celery.tasks["app.tasks.matching.populate_submitters"]

    task.apply_async(args=(match_id, config_id, current_user.id, task_id), task_id=task_id)

    return redirect(url)


@admin.route("/manage_assessments")
@roles_required("root")
def manage_assessments():
    """
    Create the 'manage assessments' view
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    return render_template_context("admin/presentations/manage.html")


@admin.route("/presentation_assessments_ajax")
@roles_required("root")
def presentation_assessments_ajax():
    """
    AJAX endpoint to generate data for populating the 'manage assessments' view
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    current_year = get_current_year()
    assessments = db.session.query(PresentationAssessment).filter_by(year=current_year).all()

    return ajax.admin.presentation_assessments_data(assessments)


@admin.route("/add_assessment", methods=["GET", "POST"])
@roles_required("root")
def add_assessment():
    """
    Add a new named assessment event
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    current_year = get_current_year()
    AddPresentationAssessmentForm = AddPresentationAssessmentFormFactory(current_year)
    form = AddPresentationAssessmentForm(request.form)

    if not hasattr(form, "submission_periods"):
        flash("An internal error occurred. Please contact a system administrator", "error")
        return redirect(redirect_url())

    if form.validate_on_submit():
        data = PresentationAssessment(
            name=form.name.data,
            year=current_year,
            submission_periods=form.submission_periods.data,
            requested_availability=False,
            availability_closed=False,
            availability_deadline=None,
            skip_availability=False,
            availability_skipped_id=None,
            availability_skipped_timestamp=None,
            feedback_open=True,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        db.session.add(data)
        db.session.commit()

        return redirect(url_for("admin.manage_assessments"))

    return render_template_context("admin/presentations/edit_assessment.html", form=form, title="Add new presentation assessment event")


@admin.route("/edit_assessment/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_assessment(id):
    """
    Edit an existing named assessment event
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if assessment.requested_availability:
        flash("It is no longer possible to change settings for an assessment once availability requests have been issued.", "info")
        return redirect(redirect_url())

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    EditPresentationAssessmentForm = EditPresentationAssessmentFormFactory(current_year, assessment)
    form = EditPresentationAssessmentForm(obj=assessment)
    form.assessment = assessment

    if form.validate_on_submit():
        assessment.name = form.name.data

        if hasattr(form, "submission_periods"):
            assessment.submission_periods = form.submission_periods.data

        assessment.last_edit_id = current_user.id
        assessment.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for("admin.manage_assessments"))

    return render_template_context(
        "admin/presentations/edit_assessment.html", form=form, assessment=assessment, title="Edit existing presentation assessment event"
    )


@admin.route("/delete_assessment/<int:id>")
@roles_required("root")
def delete_assessment(id):
    """
    Delete an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash('Assessment "{name}" has a deployed schedule and cannot be deleted.'.format(name=assessment.name), "info")
        return redirect(redirect_url())

    title = "Delete presentation assessment"
    panel_title = "Delete presentation assessment <strong>{name}</strong>".format(name=assessment.name)

    action_url = url_for("admin.perform_delete_assessment", id=id, url=request.referrer)
    message = (
        "<p>Please confirm that you wish to delete the assessment "
        "<strong>{name}</strong>.</p>"
        "<p>This action cannot be undone.</p>".format(name=assessment.name)
    )
    submit_label = "Delete assessment"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/perform_delete_assessment/<int:id>")
@roles_required("root")
def perform_delete_assessment(id):
    """
    Delete an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash('Assessment "{name}" has a deployed schedule and cannot be deleted.'.format(name=assessment.name), "info")
        return redirect(redirect_url())

    url = request.args.get("url", url_for("admin.manage_assessments"))

    db.session.delete(assessment)
    db.session.commit()

    return redirect(url)


@admin.route("/close_assessment/<int:id>")
@roles_required("root")
def close_assessment(id):
    """
    Close feedback for an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.is_feedback_open:
        return redirect(redirect_url())

    if not assessment.is_closable:
        flash(
            'Cannot close assessment "{name}" because one or more closing criteria have not been met. Check '
            "that all scheduled sessions are in the past.".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    title = "Close feedback for assessment"
    panel_title = "Close feedback for assessment <strong>{name}</strong>".format(name=assessment.name)

    action_url = url_for("admin.perform_close_assessment", id=id, url=request.referrer)
    message = (
        "<p>Please confirm that you wish to close feedback for the assessment "
        "<strong>{name}</strong>.</p>"
        "<p>This action cannot be undone.</p>".format(name=assessment.name)
    )
    submit_label = "Close feedback"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/perform_close_assessment/<int:id>")
@roles_required("root")
def perform_close_assessment(id):
    """
    Close feedback for an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.is_feedback_open:
        return redirect(redirect_url())

    if not assessment.is_closable:
        flash(
            'Cannot close assessment "{name}" because one or more closing criteria have not been met. Check '
            "that all scheduled sessions are in the past.".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    url = request.args.get("url", url_for("admin.manage_assessments"))

    assessment.is_feedback_open = False
    db.session.commit()

    return redirect(url)


@admin.route("/initialize_assessment/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def initialize_assessment(id):
    """
    Initialize an assessment by requesting availability information from faculty, or optionally skip that
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.is_valid and assessment.availability_lifecycle < PresentationAssessment.AVAILABILITY_REQUESTED:
        flash("Cannot request availability for an invalid assessment. Correct any validation errors before attempting to proceed.", "info")
        return redirect(redirect_url())

    return_url = url_for("admin.manage_assessments")

    AvailabilityForm = AvailabilityFormFactory(assessment)
    form: AvailabilityForm = AvailabilityForm(obj=assessment)

    if form.is_submitted():
        if hasattr(form, "issue_requests") and form.issue_requests.data:
            if assessment.skip_availability:
                flash("Cannot issue availability requests because they have been skipped for this assessment", "info")
                return redirect(return_url)

            if not assessment.requested_availability:
                if get_count(assessment.submission_periods) == 0:
                    flash("Availability requests not issued since this assessment is not attached to any submission periods", "info")
                    return redirect(return_url)

                if get_count(assessment.sessions) == 0:
                    flash("Availability requests not issued since this assessment does not contain any sessions", "info")
                    return redirect(return_url)

                _do_initialize_assessment(
                    'Issue availability requests for "{name}"'.format(name=assessment.name),
                    "Issue availability requests to faculty assessors",
                    assessment.id,
                    form.availability_deadline.data,
                    False,
                )

            return redirect(return_url)

    else:
        if request.method == "GET":
            if form.availability_deadline.data is None:
                form.availability_deadline.data = date.today() + timedelta(weeks=2)

    if PresentationAssessment.AVAILABILITY_NOT_REQUESTED < assessment.availability_lifecycle < PresentationAssessment.AVAILABILITY_SKIPPED:
        if hasattr(form, "issue_requests"):
            form.issue_requests.label.text = "Save changes"

    return render_template_context("admin/presentations/availability.html", form=form, assessment=assessment)


def _do_initialize_assessment(title: str, description: str, assessment_id: int, deadline: datetime, skip_availability: bool):
    uuid = register_task(title, owner=current_user, description=description)
    celery = current_app.extensions["celery"]
    availability_task = celery.tasks["app.tasks.availability.initialize"]
    availability_task.apply_async(args=(assessment_id, current_user.id, uuid, deadline, skip_availability), task_id=uuid)


@admin.route("/skip_availability/<int:id>")
@roles_required("root")
def skip_availability(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    return_url = url_for("admin.manage_assessments")

    current_year = get_current_year()

    if not validate_assessment(assessment, current_year=current_year):
        return redirect(return_url)

    if assessment.requested_availability:
        flash("Cannot skip availability collection for this assessment because it has already been opened", "info")
        return redirect(return_url)

    if not assessment.skip_availability:
        _do_initialize_assessment(
            'Attach assessor and submitter records for "{name}"'.format(name=assessment.name),
            "Attach assessor and submitter records",
            assessment.id,
            None,
            True,
        )

    return redirect(return_url)


@admin.route("/close_availability/<int:id>")
@roles_required("root")
def close_availability(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash("Cannot close availability collection for this assessment because it has not yet been opened", "info")
        return redirect(redirect_url())

    if assessment.skip_availability:
        flash("Cannot close availability collection for this assessment because it has been skipped", "info")
        return redirect(redirect_url())

    assessment.availability_closed = True
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/availability_reminder/<int:id>")
@roles_required("root")
def availability_reminder(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash("Cannot issue reminder emails for this assessment because availability collection has not yet been opened", "info")
        return redirect(redirect_url())

    if assessment.skip_availability:
        flash("Cannot issue reminder emails for this assessment because availabilty collection has been skipped", "info")
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    email_task = celery.tasks["app.tasks.availability.reminder_email"]

    email_task.apply_async((id, current_user.id))

    return redirect(redirect_url())


@admin.route("/availability_reminder_individual/<int:id>")
@roles_required("root")
def availability_reminder_individual(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    record: AssessorAttendanceData = AssessorAttendanceData.query.get_or_404(id)
    assessment: PresentationAssessment = record.assessment

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash("Cannot send a reminder email for this assessment because availability collection has not yet been opened", "info")
        return redirect(redirect_url())

    if assessment.skip_availability:
        flash("Cannot issue a reminder email for this assessment because availability collection has been skipped", "info")
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    email_task = celery.tasks["app.tasks.availability.send_reminder_email"]
    notify_task = celery.tasks["app.tasks.utilities.email_notification"]

    tk = email_task.si(record.id) | notify_task.s(current_user.id, "Reminder email has been sent", "info")
    tk.apply_async()

    return redirect(redirect_url())


@admin.route("/reopen_availability/<int:id>")
@roles_required("root")
def reopen_availability(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if assessment.skip_availability:
        flash("Cannot reopen availability collection for this assessment because it has been skipped", "info")
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash("Cannot reopen availability collection for this assessment because it has not yet been opened", "info")
        return redirect(redirect_url())

    if not assessment.availability_closed:
        flash("Cannot reopen availability collection for this assessment because it has not yet been closed", "info")
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash("Cannot reopen availability collection for this assessment because it has a deployed schedule", "info")
        return redirect(redirect_url())

    assessment.availability_closed = False
    if assessment.availability_deadline < date.today():
        assessment.availability_deadline = date.today() + timedelta(weeks=1)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/outstanding_availability/<int:id>")
@roles_required("root")
def outstanding_availability(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash("Cannot show outstanding availability responses for this assessment because it has not yet been opened", "info")
        return redirect(redirect_url())

    return render_template_context("admin/presentations/availability/outstanding.html", assessment=assessment)


@admin.route("/outstanding_availability_ajax/<int:id>")
@roles_required("root")
def outstanding_availability_ajax(id):
    if not validate_using_assessment():
        return jsonify({})

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return jsonify({})

    if not assessment.requested_availability:
        flash("Cannot show outstanding availability responses for this assessment because it has not yet been opened", "info")
        return jsonify({})

    return ajax.admin.outstanding_availability_data(assessment.outstanding_assessors.all(), assessment)


@admin.route("/force_confirm_availability/<int:assessment_id>/<int:faculty_id>")
@roles_required("root")
def force_confirm_availability(assessment_id, faculty_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(assessment_id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash("Cannot force confirm an availability response for this assessment because it has not yet been opened", "info")
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash("Cannot force confirm availability for this assessment because it is currently deployed", "info")
        return redirect(redirect_url())

    faculty: FacultyData = FacultyData.query.get_or_404(faculty_id)

    if not assessment.includes_faculty(faculty_id):
        flash(
            "Cannot force confirm availability response for {name} because this faculty member is not attached "
            "to this assessment".format(name=faculty.user.name),
            "error",
        )
        return redirect(redirect_url())

    record = assessment.assessor_list.filter_by(faculty_id=faculty_id, confirmed=False).first()

    if record is not None:
        record.confirmed = True
        record.confirmed_timestamp = datetime.now()
        db.session.commit()

    return redirect(redirect_url())


@admin.route("/set_assignment_limit/<int:assessment_id>/<int:faculty_id>", methods=["GET", "POST"])
@roles_required("root")
def schedule_set_limit(assessment_id, faculty_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(assessment_id)

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    if url is None:
        url = url_for("admin.assessment_manage_assessors", id=assessment_id)
        text = "assessment assessor list"

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(url)

    if not assessment.requested_availability and not assessment.skip_availability:
        flash("Cannot adjust limits from this assessment because availability collection has not yet been opened", "info")
        return redirect(url)

    if assessment.is_deployed:
        flash("Cannot adjust limits for this assessment because it is currently deployed", "info")
        return redirect(url)

    faculty: FacultyData = FacultyData.query.get_or_404(faculty_id)

    if not assessment.includes_faculty(faculty_id):
        flash(
            'Cannot remove assessor "{name}" from "{assess_name}" because this faculty member is not attached '
            "to this assessment".format(name=faculty.user.name, assess_name=assessment.name),
            "error",
        )
        return redirect(url)

    record = assessment.assessor_list.filter_by(faculty_id=faculty_id).first()

    if record is None:
        return redirect(url)

    form = AssignmentLimitForm(obj=record)

    if form.validate_on_submit():
        record.assigned_limit = form.assigned_limit.data
        db.session.commit()

        return redirect(url)

    return render_template_context(
        "admin/presentations/edit_assigned_limit.html", form=form, fac=faculty, rec=record, a=assessment, url=url, text=text
    )


@admin.route("/remove_assessor/<int:assessment_id>/<int:faculty_id>")
@roles_required("root")
def remove_assessor(assessment_id, faculty_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(assessment_id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash("Cannot remove assessors from this assessment because it has not yet been opened", "info")
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash("Cannot remove assessors from this assessment because it is currently deployed", "info")
        return redirect(redirect_url())

    faculty: FacultyData = FacultyData.query.get_or_404(faculty_id)

    if not assessment.includes_faculty(faculty_id):
        flash(
            'Cannot remove assessor "{name}" from "{assess_name}" because this faculty member is not attached '
            "to this assessment".format(name=faculty.user.name, assess_name=assessment.name),
            "error",
        )
        return redirect(redirect_url())

    record = assessment.assessor_list.filter_by(faculty_id=faculty_id).first()

    if record is not None:
        db.session.delete(record)
        db.session.commit()

    return redirect(redirect_url())


@admin.route("/availability_as_csv/<int:id>")
@roles_required("root")
def availability_as_csv(id):
    """
    Convert availability data to CSV and serve
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash("Cannot generate availability data for this assessment because it has not yet been collected.", "info")
        return redirect(redirect_url())

    # add a filename
    headers = Headers()
    headers.set("Content-Disposition", "attachment", filename="availability.csv")

    # stream the response as the data is generated
    return Response(stream_with_context(availability_CSV_generator(assessment)), mimetype="text/csv", headers=headers)


@admin.route("/assessment_manage_sessions/<int:id>")
@roles_required("root")
def assessment_manage_sessions(id):
    """
    Manage dates for an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    return render_template_context("admin/presentations/manage_sessions.html", assessment=assessment)


@admin.route("/manage_sessions_ajax/<int:id>")
@roles_required("root")
def manage_sessions_ajax(id):
    if not validate_using_assessment():
        return jsonify({})

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(assessment):
        return jsonify({})

    return ajax.admin.assessment_sessions_data(assessment.sessions)


@admin.route("/add_session/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def add_session(id):
    """
    Attach a new session to the specified assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if not assessment.is_feedback_open:
        flash('Event "{name}" has been closed to feedback and its sessions can no longer be ' "edited".format(name=assessment.name), "info")
        return redirect(redirect_url())

    form = AddSessionForm(request.form)

    if form.validate_on_submit():
        sess = PresentationSession(
            owner_id=assessment.id,
            name=form.name.data,
            date=form.date.data,
            session_type=form.session_type.data,
            rooms=form.rooms.data,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            db.session.add(sess)
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            flash("Could not add new session due to a database error. Please contact a system administrator.", "error")

        else:
            # add this session to all attendance data records attached for this assessment
            celery = current_app.extensions["celery"]
            adjust_task = celery.tasks["app.tasks.availability.session_added"]

            adjust_task.apply_async(args=(sess.id, assessment.id))

        return redirect(url_for("admin.assessment_manage_sessions", id=id))

    return render_template_context("admin/presentations/edit_session.html", form=form, assessment=assessment)


@admin.route("/edit_session/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_session(id):
    """
    Edit an existing assessment event session
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(id)

    if not validate_assessment(sess.owner):
        return redirect(redirect_url())

    if not sess.owner.is_feedback_open:
        flash('Event "{name}" has been closed to feedback and its sessions can no longer be ' "edited".format(name=sess.owner.name), "info")
        return redirect(redirect_url())

    form = EditSessionForm(obj=sess)
    form.session = sess

    if form.validate_on_submit():
        sess.name = form.name.data
        sess.date = form.date.data
        sess.session_type = form.session_type.data
        sess.rooms = form.rooms.data

        sess.last_edit_id = current_user.id
        sess.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            flash("Could not save edited session data due to a database error. Please contact a system administrator.", "error")

        return redirect(url_for("admin.assessment_manage_sessions", id=sess.owner_id))

    return render_template_context("admin/presentations/edit_session.html", form=form, assessment=sess.owner, sess=sess)


@admin.route("/delete_session/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def delete_session(id):
    """
    Delete the specified session from an assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(id)

    if not validate_assessment(sess.owner):
        return redirect(redirect_url())

    if not sess.owner.is_feedback_open:
        flash('Event "{name}" has been closed to feedback and its sessions can no longer be ' "edited".format(name=sess.owner.name), "info")
        return redirect(redirect_url())

    # deletion can't be done asynchronously, because we want the database to be updated
    # by the time the user's UI is refreshed

    for assessor in sess.owner.assessor_list:
        if sess in assessor.available:
            assessor.available.remove(sess)
        if sess in assessor.unavailable:
            assessor.unavailable.remove(sess)
        if sess in assessor.if_needed:
            assessor.if_needed.remove(sess)

    for submitter in sess.owner.submitter_list:
        if sess in submitter.available:
            submitter.available.remove(sess)
        if sess in submitter.unavailable:
            submitter.unavailable.remove(sess)

    db.session.delete(sess)
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/manage_attendees_ajax/<int:id>")
@roles_required("root")
def manage_attendees_ajax(id):
    """
    AJAX data point for managing student attendees
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(data):
        return jsonify({})

    pclass_filter = request.args.get("pclass_filter")
    attend_filter = request.args.get("attend_filter")

    talks: List[SubmitterAttendanceData] = data.submitter_list

    flag, pclass_value = is_integer(pclass_filter)
    if flag:
        talks = [t for t in talks if t.submitter.owner.config.pclass_id == pclass_value]

    if attend_filter == "attending":
        talks = [t for t in talks if t.attending]
    elif attend_filter == "not-attending":
        talks = [t for t in talks if not t.attending]

    return ajax.admin.presentation_attendees_data(data, talks, editable=not data.is_deployed)


@admin.route("/assessment_attending/<int:a_id>/<int:s_id>")
@roles_required("root")
def assessment_attending(a_id, s_id):
    """
    Mark a student/talk as able to attend the assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    if not validate_assessment(data):
        return redirect(redirect_url())

    if data.is_deployed:
        flash('Assessment "{name}" has a deployed schedule, and its attendees can no longer be ' "altered".format(name=data.name), "info")
        return redirect(redirect_url())

    talk: SubmissionRecord = SubmissionRecord.query.get_or_404(s_id)

    if talk not in data.available_talks:
        flash("Cannot mark the specified presenter as attending because they are not included in this presentation assessment", "error")
        return redirect(redirect_url())

    data.submitter_attending(talk)
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/assessment_not_attending/<int:a_id>/<int:s_id>")
@roles_required("root")
def assessment_not_attending(a_id, s_id):
    """
    Mark a student/talk as not able to attend the assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    if not validate_assessment(data):
        return redirect(redirect_url())

    if data.is_deployed:
        flash('Assessment "{name}" has a deployed schedule, and its attendees can no longer be ' "altered".format(name=data.name), "info")
        return redirect(redirect_url())

    talk = SubmissionRecord.query.get_or_404(s_id)

    if talk not in data.available_talks:
        flash("Cannot mark the specified presenter as not attending because they are not included in this presentation assessment", "error")
        return redirect(redirect_url())

    data.submitter_not_attending(talk)
    db.session.commit()

    # we leave availability information per-session intact, so that it is immediately available again
    # if this presenter is subsequently marked as attending

    return redirect(redirect_url())


@admin.route("/assessment_submitter_availability/<int:a_id>/<int:s_id>")
@roles_required("root")
def assessment_submitter_availability(a_id, s_id):
    """
    Allow submitter availabilities to be specified on a per-session basis
    :param a_id:
    :param s_id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    if not validate_assessment(data):
        return redirect(redirect_url())

    submitter: SubmissionRecord = SubmissionRecord.query.get_or_404(s_id)

    if not data.includes_submitter(s_id):
        flash("Cannot set availability for the specified presenter because they are not included in this presentation assessment", "error")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    return render_template_context(
        "admin/presentations/availability/submitter_availability.html", assessment=data, submitter=submitter, url=url, text=text
    )


@admin.route("/assessment_assessor_availability/<int:a_id>/<int:f_id>")
@roles_required("root")
def assessment_assessor_availability(a_id, f_id):
    """
    Allow submitter availabilities to be specified on a per-session basis
    :param a_id:
    :param s_id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    if not validate_assessment(data):
        return redirect(redirect_url())

    assessor: FacultyData = FacultyData.query.get_or_404(f_id)

    if not data.includes_faculty(f_id):
        flash("Cannot set availability for the specified assessor because they are not included in this presentation assessment", "error")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    return render_template_context(
        "admin/presentations/availability/assessor_availability.html", assessment=data, assessor=assessor, url=url, text=text
    )


@admin.route("/submitter_session_availability/<int:id>")
@roles_required("root")
def submitter_session_availability(id):
    """
    Edit/inspect submitter availabilities per session
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(id)

    if sess.owner.is_deployed:
        flash('Assessment "{name}" has a deployed schedule, and its attendees can no longer be' " altered".format(name=sess.owner.name), "info")
        return redirect(redirect_url())

    if not validate_assessment(sess.owner):
        return redirect(redirect_url())

    pclass_filter = request.args.get("pclass_filter")

    if pclass_filter is None and session.get("attendees_session_pclass_filter"):
        pclass_filter = session["attendees_session_pclass_filter"]

    if pclass_filter is not None:
        session["attendees_session_pclass_filter"] = pclass_filter

    pclasses = sess.owner.available_pclasses

    return render_template_context(
        "admin/presentations/availability/submitter_session_availability.html",
        assessment=sess.owner,
        sess=sess,
        pclass_filter=pclass_filter,
        pclasses=pclasses,
    )


@admin.route("/submitter_session_availability_ajax/<int:id>")
@roles_required("root")
def submitter_session_availability_ajax(id):
    """
    AJAX endpoint for edit/inspect submitter availability per session
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    sess: PresentationSession = PresentationSession.query.get_or_404(id)

    if sess.owner.is_deployed:
        return jsonify({})

    if not validate_assessment(sess.owner):
        return jsonify({})

    pclass_filter = request.args.get("pclass_filter")

    data = sess.owner
    talks = data.submitter_list.filter_by(attending=True)  # only include students who are marked as attending
    flag, pclass_value = is_integer(pclass_filter)
    if flag:
        talks = [t for t in talks if t.submitter.owner.config.pclass_id == pclass_value]

    return ajax.admin.submitter_session_availability_data(data, sess, talks, editable=not sess.owner.is_deployed)


@admin.route("/submitter_available/<int:sess_id>/<int:s_id>")
@roles_accepted("root")
def submitter_available(sess_id, s_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess = PresentationSession.query.get_or_404(sess_id)
    data = sess.owner

    if not validate_assessment(data):
        return redirect(redirect_url())

    if data.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=data.name),
            "info",
        )
        return redirect(redirect_url())

    submitter = SubmissionRecord.query.get_or_404(s_id)

    if submitter not in data.available_talks:
        flash("Cannot specify availability for the specified presenter because they are not included in this presentation assessment", "error")
        return redirect(redirect_url())

    sess.submitter_make_available(submitter)
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/submitter_unavailable/<int:sess_id>/<int:s_id>")
@roles_accepted("root")
def submitter_unavailable(sess_id, s_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    data = sess.owner

    if not validate_assessment(data):
        return redirect(redirect_url())

    if data.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=data.name),
            "info",
        )
        return redirect(redirect_url())

    submitter: SubmissionRecord = SubmissionRecord.query.get_or_404(s_id)

    if submitter not in data.available_talks:
        flash("Cannot specify availability for the specified presenter because they are not included in this presentation assessment", "error")
        return redirect(redirect_url())

    sess.submitter_make_unavailable(submitter)
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/submitter_available_all_sessions/<int:a_id>/<int:s_id>")
@roles_accepted("root")
def submitter_available_all_sessions(a_id, s_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash('Assessment "{name}" has a deployed schedule, and its attendees can no longer be ' "altered".format(name=assessment.name), "info")
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash("Cannot change availability because collection for its parent assessment has not yet been opened", "info")
        return redirect(redirect_url())

    submitter: SubmissionRecord = SubmissionRecord.query.get_or_404(s_id)

    if submitter not in assessment.available_talks:
        flash("Cannot specify availability for the specified presenter because they are not included in this presentation assessment", "error")
        return redirect(redirect_url())

    for s in assessment.sessions:
        s.submitter_make_available(submitter)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/submitter_unavailable_all_sessions/<int:a_id>/<int:s_id>")
@roles_accepted("root")
def submitter_unavailable_all_sessions(a_id, s_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash('Assessment "{name}" has a deployed schedule, and its attendees can no longer be ' "altered".format(name=assessment.name), "info")
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash("Cannot change availability because collection for its parent assessment has not yet been opened", "info")
        return redirect(redirect_url())

    submitter: SubmissionRecord = SubmissionRecord.query.get_or_404(s_id)

    if submitter not in assessment.available_talks:
        flash("Cannot specify availability for the specified presenter because they are not included in this presentation assessment", "error")
        return redirect(redirect_url())

    for s in assessment.sessions:
        s.submitter_make_unavailable(submitter)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/session_all_submitters_available/<int:sess_id>")
@roles_accepted("root")
def session_all_submitters_available(sess_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = sess.owner

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash("Cannot change availability because collection for its parent assessment has not yet been opened", "info")
        return redirect(redirect_url())

    for s in assessment.submitter_list:
        s: SubmitterAttendanceData
        rec: SubmissionRecord = s.submitter

        sess.submitter_make_available(rec)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/session_all_submitters_unavailable/<int:sess_id>")
@roles_accepted("root")
def session_all_submitters_unavailable(sess_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = sess.owner

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash("Cannot change availability because collection for its parent assessment has not yet been opened", "info")
        return redirect(redirect_url())

    for s in assessment.submitter_list:
        s: SubmitterAttendanceData
        rec: SubmissionRecord = s.submitter

        sess.submitter_make_unavailable(rec)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/assessment_manage_assessors/<int:id>")
@roles_required("root")
def assessment_manage_assessors(id):
    """
    Manage faculty assessors for an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(data):
        return redirect(redirect_url())

    state_filter = request.args.get("state_filter")

    if state_filter is None and session.get("assessors_state_filter"):
        state_filter = session["assessors_state_filter"]

    if state_filter is not None:
        session["assessors_state_filter"] = state_filter

    return render_template_context("admin/presentations/manage_assessors.html", assessment=data, state_filter=state_filter)


@admin.route("/manage_assessors_ajax/<int:id>")
@roles_required("root")
def manage_assessors_ajax(id):
    """
    AJAX data point for managing faculty assessors
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    state_filter = request.args.get("state_filter")

    if state_filter == "confirm":
        attached_q = data.assessor_list.subquery()

        assessors = (
            db.session.query(AssessorAttendanceData)
            .join(attached_q, attached_q.c.id == AssessorAttendanceData.id)
            .filter(AssessorAttendanceData.confirmed == True)
            .all()
        )

    elif state_filter == "not-confirm":
        attached_q = data.assessor_list.subquery()

        assessors = (
            db.session.query(AssessorAttendanceData)
            .join(attached_q, attached_q.c.id == AssessorAttendanceData.id)
            .filter(AssessorAttendanceData.confirmed == False)
            .all()
        )

    else:
        assessors = data.assessor_list.all()

    return ajax.admin.presentation_assessors_data(data, assessors, editable=not data.is_deployed)


@admin.route("/assessor_session_availability/<int:id>")
@roles_required("root")
def assessor_session_availability(id):
    """
    Edit/inspect faculty availabilities for an assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(id)

    if not sess.owner.is_feedback_open:
        flash('Event "{name}" has been closed to feedback and its sessions can no longer be ' "edited".format(name=sess.owner.name), "info")
        return redirect(redirect_url())

    if not validate_assessment(sess.owner):
        return redirect(redirect_url())

    state_filter = request.args.get("state_filter")

    if state_filter is None and session.get("assessors_session_state_filter"):
        state_filter = session["assessors_session_state_filter"]

    if state_filter is not None:
        session["assessors_session_state_filter"] = state_filter

    return render_template_context(
        "admin/presentations/availability/assessor_session_availability.html", assessment=sess.owner, sess=sess, state_filter=state_filter
    )


@admin.route("/assessor_session_availability_ajax/<int:id>")
@roles_required("root")
def assessor_session_availability_ajax(id):
    """
    AJAX data entrypoint for edit/inspect faculty availability viee
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    sess: PresentationSession = PresentationSession.query.get_or_404(id)

    if not validate_assessment(sess.owner):
        return jsonify({})

    state_filter = request.args.get("state_filter")
    data = sess.owner

    if state_filter == "confirm":
        attached_q = data.assessor_list.subquery()

        assessors = (
            db.session.query(AssessorAttendanceData)
            .join(attached_q, attached_q.c.id == AssessorAttendanceData.id)
            .filter(AssessorAttendanceData.confirmed == True)
            .all()
        )

    elif state_filter == "not-confirm":
        attached_q = data.assessor_list.subquery()

        assessors = (
            db.session.query(AssessorAttendanceData)
            .join(attached_q, attached_q.c.id == AssessorAttendanceData.id)
            .filter(AssessorAttendanceData.confirmed == False)
            .all()
        )

    else:
        assessors = data.assessor_list.all()

    return ajax.admin.assessor_session_availability_data(data, sess, assessors, editable=not sess.owner.is_deployed)


@admin.route("/assessor_available/<int:sess_id>/<int:f_id>")
@roles_accepted("root")
def assessor_available(sess_id, f_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = sess.owner

    current_year = get_current_year()
    if not validate_assessment(sess.owner, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash("Cannot change availability because collection for its parent assessment has not yet been opened", "info")
        return redirect(redirect_url())

    fac: FacultyData = FacultyData.query.get_or_404(f_id)
    sess.faculty_make_available(fac)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/assessor_ifneeded/<int:sess_id>/<int:f_id>")
@roles_accepted("root")
def assessor_ifneeded(sess_id, f_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = sess.owner

    current_year = get_current_year()
    if not validate_assessment(sess.owner, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash("Cannot change availability because collection for its parent assessment has not yet been opened", "info")
        return redirect(redirect_url())

    fac: FacultyData = FacultyData.query.get_or_404(f_id)
    sess.faculty_make_ifneeded(fac)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/assessor_unavailable/<int:sess_id>/<int:f_id>")
@roles_accepted("root")
def assessor_unavailable(sess_id, f_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = sess.owner

    current_year = get_current_year()
    if not validate_assessment(sess.owner, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash("Cannot change availability because collection for its parent assessment has not yet been opened", "info")
        return redirect(redirect_url())

    fac: FacultyData = FacultyData.query.get_or_404(f_id)
    sess.faculty_make_unavailable(fac)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/assessor_available_all_sessions/<int:a_id>/<int:f_id>")
@roles_accepted("root")
def assessor_available_all_sessions(a_id, f_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash('Assessment "{name}" has a deployed schedule, and its attendees can no longer be ' "altered".format(name=assessment.name), "info")
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash("Cannot change availability because collection for its parent assessment has not yet been opened", "info")
        return redirect(redirect_url())

    fac: FacultyData = FacultyData.query.get_or_404(f_id)

    for s in assessment.sessions:
        s.faculty_make_available(fac)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/assessor_unavailable_all_sessions/<int:a_id>/<int:f_id>")
@roles_accepted("root")
def assessor_unavailable_all_sessions(a_id, f_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(a_id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash('Assessment "{name}" has a deployed schedule, and its attendees can no longer be ' "altered".format(name=assessment.name), "info")
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash("Cannot change availability because collection for its parent assessment has not yet been opened", "info")
        return redirect(redirect_url())

    fac: FacultyData = FacultyData.query.get_or_404(f_id)

    for s in assessment.sessions:
        s.faculty_make_unavailable(fac)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/session_all_assessors_available/<int:sess_id>")
@roles_accepted("root")
def session_all_assessors_available(sess_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = sess.owner

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash("Cannot change availability because collection for its parent assessment has not yet been opened", "info")
        return redirect(redirect_url())

    for f in assessment.assessor_list:
        f: AssessorAttendanceData
        fac: FacultyData = f.faculty

        sess.faculty_make_available(fac)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/session_all_assessors_unavailable/<int:sess_id>")
@roles_accepted("root")
def session_all_assessors_unavailable(sess_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    sess: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = sess.owner

    if not validate_assessment(assessment):
        return redirect(redirect_url())

    if assessment.is_deployed:
        flash(
            'Assessment "{name}" has a deployed schedule, and availability status for its attendees can no longer be '
            "altered".format(name=assessment.name),
            "info",
        )
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash("Cannot change availability because collection for its parent assessment has not yet been opened", "info")
        return redirect(redirect_url())

    for f in assessment.assessor_list:
        f: AssessorAttendanceData
        fac: FacultyData = f.faculty

        sess.faculty_make_unavailable(fac)

    db.session.commit()

    return redirect(redirect_url())


@admin.route("/assessment_schedules/<int:id>")
@roles_required("root")
def assessment_schedules(id):
    """
    Manage schedules associated with a given assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.availability_closed and not assessment.skip_availability:
        flash("It is only possible to generate schedules once collection of faculty availabilities is closed (or has been skipped).", "info")
        return redirect(redirect_url())

    matches = get_count(assessment.scheduling_attempts)

    return render_template_context("admin/presentations/scheduling/manage.html", pane="manage", info=matches, assessment=assessment)


@admin.route("/assessment_schedules_ajax/<int:id>")
@roles_required("root")
def assessment_schedules_ajax(id):
    """
    AJAX data point for schedules associated with a given assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return jsonify({})

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return jsonify({})

    if not assessment.availability_closed and not assessment.skip_availability:
        return jsonify({})

    return ajax.admin.assessment_schedules_data(
        assessment.scheduling_attempts, text="assessment schedule manager", url=url_for("admin.assessment_schedules", id=id)
    )


@admin.route("/create_assessment_schedule/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def create_assessment_schedule(id):
    """
    Create a new schedule associated with a given assessment
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.availability_closed and not assessment.skip_availability:
        flash("It is only possible to generate schedules once collection of faculty availabilities is closed (or has been skipped).", "info")
        return redirect(redirect_url())

    if not assessment.is_valid:
        flash(
            "It is not possible to generate a schedule for an assessment that contains validation errors. "
            "Correct any indicated errors before attempting to try again.",
            "info",
        )
        return redirect(redirect_url())

    if assessment.number_slots <= 0:
        flash("It is not possible to generate a schedule for this assessment, because it does not yet have any defined session slots.", "info")
        return redirect(redirect_url())

    NewScheduleForm = NewScheduleFormFactory(assessment)
    form = NewScheduleForm(request.form)

    if form.validate_on_submit():
        offline = False

        if form.submit.data:
            task_name = 'Perform optimal scheduling for "{name}"'.format(name=form.name.data)
            desc = "Automated assessment scheduling task"

        elif form.offline.data:
            offline = True
            task_name = 'Generate file for offline scheduling for "{name}"'.format(name=form.name.data)
            desc = "Produce .LP file for download and offline scheduling"

        else:
            raise RuntimeError("Unknown submit button in create_assessment_schedule()")

        uuid = register_task(task_name, owner=current_user, description=desc)

        schedule = ScheduleAttempt(
            owner_id=assessment.id,
            name=form.name.data,
            tag=form.tag.data,
            celery_id=uuid,
            finished=False,
            awaiting_upload=offline,
            celery_finished=False,
            outcome=None,
            published=False,
            deployed=False,
            construct_time=None,
            compute_time=None,
            assessor_assigned_limit=form.assessor_assigned_limit.data,
            assessor_multiplicity_per_session=form.assessor_multiplicity_per_session.data,
            if_needed_cost=form.if_needed_cost.data,
            levelling_tension=form.levelling_tension.data,
            ignore_coscheduling=form.ignore_coscheduling.data,
            all_assessors_in_pool=form.all_assessors_in_pool.data,
            solver=form.solver.data,
            creation_timestamp=datetime.now(),
            creator_id=current_user.id,
            last_edit_timestamp=None,
            last_edit_id=None,
            score=None,
            lp_file_id=None,
        )

        db.session.add(schedule)
        db.session.commit()

        if offline:
            celery = current_app.extensions["celery"]
            schedule_task = celery.tasks["app.tasks.scheduling.offline_schedule"]

            schedule_task.apply_async(args=(schedule.id, current_user.id), task_id=uuid)

            return redirect(url_for("admin.assessment_schedules", id=assessment.id))

        else:
            celery = current_app.extensions["celery"]
            schedule_task = celery.tasks["app.tasks.scheduling.create_schedule"]

            schedule_task.apply_async(args=(schedule.id,), task_id=uuid)

            return redirect(url_for("admin.assessment_schedules", id=assessment.id))

    else:
        if request.method == "GET":
            form.all_assessors_in_pool.data = ScheduleAttempt.AT_LEAST_ONE_IN_POOL

    matches = get_count(assessment.scheduling_attempts)

    return render_template_context("admin/presentations/scheduling/create.html", pane="create", info=matches, form=form, assessment=assessment)


@admin.route("/adjust_assessment_schedule/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def adjust_assessment_schedule(id):
    """
    Generate options page for re-imposition of constraints
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    schedule: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)
    assessment: PresentationAssessment = schedule.owner

    current_year = get_current_year()
    if not validate_assessment(schedule.owner, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.availability_closed and not assessment.skip_availability:
        flash("It is only possible to adjust a schedule once collection of faculty availabilities is closed (or has been skipped).", "info")
        return redirect(redirect_url())

    if not assessment.is_valid:
        flash(
            "It is not possible to adjust a schedule for an assessment that contains validation errors. "
            "Correct any indicated errors before attempting to try again.",
            "info",
        )
        return redirect(redirect_url())

    if schedule.is_valid:
        flash("This schedule does not contain any validation errors, so does not require adjustment.", "info")
        return redirect(redirect_url())

    ImposeConstraintsScheduleForm = ImposeConstraintsScheduleFormFactory(assessment)
    form = ImposeConstraintsScheduleForm(request.form)

    if form.validate_on_submit():
        allow_new_slots = form.allow_new_slots.data
        name = form.name.data
        tag = form.tag.data

        return redirect(url_for("admin.perform_adjust_assessment_schedule", id=id, name=name, tag=tag, new_slots=allow_new_slots))

    else:
        if request.method == "GET":
            # find name for adjusted schedule
            suffix = 2
            while suffix < 100:
                new_name = "{name} #{suffix}".format(name=schedule.name, suffix=suffix)

                if ScheduleAttempt.query.filter_by(name=new_name, owner_id=schedule.owner_id).first() is None:
                    break

                suffix += 1

            if suffix > 100:
                flash('Can not adjust schedule "{name}" because a new unique tag could not ' "be generated.".format(name=schedule.name), "error")
                return redirect(redirect_url())

            form.name.data = new_name

            guess_id = db.session.query(func.max(ScheduleAttempt.id)).scalar() + 1
            new_tag = "schedule_{n}".format(n=guess_id)

            form.tag.data = new_tag

    return render_template_context("admin/presentations/scheduling/adjust_options.html", record=schedule, form=form)


@admin.route("/perform_adjust_assessment_schedule/<int:id>")
@roles_required("root")
def perform_adjust_assessment_schedule(id):
    """
    Adjust an existing schedule to re-impose constraints
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    old_schedule: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)
    assessment: PresentationAssessment = old_schedule.owner

    current_year = get_current_year()
    if not validate_assessment(old_schedule.owner, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.availability_closed and not assessment.skip_availability:
        flash("It is only possible to adjust a schedule once collection of faculty availabilities is closed (or has been skipped).", "info")
        return redirect(redirect_url())

    if not assessment.is_valid:
        flash(
            "It is not possible to adjust a schedule for an assessment that contains validation errors. "
            "Correct any indicated errors before attempting to try again.",
            "info",
        )
        return redirect(redirect_url())

    if old_schedule.is_valid:
        flash("This schedule does not contain any validation errors, so does not require adjustment.", "info")
        return redirect(redirect_url())

    new_name = request.args.get("name", None)
    new_tag = request.args.get("tag", None)

    if new_name is None:
        flash("A name for the adjusted schedule was not supplied.", "error")
        return redirect(redirect_url())

    if new_tag is None:
        flash("A tag for the adjusted schedule was not supplied.", "error")
        return redirect(redirect_url())

    allow_new_slots = request.args.get("new_slots", False)

    uuid = register_task('Schedule job "{name}"'.format(name=new_name), owner=current_user, description="Automated assessment scheduling task")

    new_schedule = ScheduleAttempt(
        owner_id=old_schedule.owner_id,
        name=new_name,
        tag=new_tag,
        celery_id=uuid,
        finished=False,
        celery_finished=False,
        awaiting_upload=False,
        outcome=None,
        published=old_schedule.published,
        construct_time=None,
        compute_time=None,
        assessor_assigned_limit=old_schedule.assessor_assigned_limit,
        assessor_multiplicity_per_session=old_schedule.assessor_multiplicity_per_session,
        if_needed_cost=old_schedule.if_needed_cost,
        levelling_tension=old_schedule.levelling_tension,
        ignore_coscheduling=old_schedule.ignore_coscheduling,
        all_assessors_in_pool=old_schedule.all_assessors_in_pool,
        solver=old_schedule.solver,
        creation_timestamp=datetime.now(),
        creator_id=current_user.id,
        last_edit_timestamp=None,
        last_edit_id=None,
        score=None,
        lp_file_id=None,
    )

    try:
        db.session.add(new_schedule)
        db.session.commit()

    except SQLAlchemyError as e:
        flash("A database error was encountered. Please check that the supplied name and tag are unique.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    schedule_task = celery.tasks["app.tasks.scheduling.recompute_schedule"]

    schedule_task.apply_async(args=(new_schedule.id, old_schedule.id, allow_new_slots), task_id=uuid)

    return redirect(url_for("admin.assessment_schedules", id=old_schedule.owner.id))


@admin.route("/terminate_schedule/<int:id>")
@roles_required("root")
def terminate_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if record.finished:
        flash('Can not terminate scheduling task "{name}" because it has finished.'.format(name=record.name), "error")
        return redirect(redirect_url())

    title = "Terminate schedule"
    panel_title = "Terminate schedule <strong>{name}</strong>".format(name=record.name)

    action_url = url_for("admin.perform_terminate_schedule", id=id, url=request.referrer)
    message = (
        "<p>Please confirm that you wish to terminate the scheduling job "
        "<strong>{name}</strong>.</p>"
        "<p>This action cannot be undone.</p>".format(name=record.name)
    )
    submit_label = "Terminate job"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/perform_terminate_schedule/<int:id>")
@roles_required("root")
def perform_terminate_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.assessment_schedules", id=record.owner_id)

    if record.finished:
        flash('Can not terminate scheduling task "{name}" because it has finished.'.format(name=record.name), "error")
        return redirect(url)

    if not record.celery_finished:
        celery = current_app.extensions["celery"]
        celery.control.revoke(record.celery_id, terminate=True, signal="SIGUSR1")

    try:
        if not record.celery_finished:
            progress_update(record.celery_id, TaskRecord.TERMINATED, 100, "Task terminated by user", autocommit=False)

        # delete all ScheduleSlot records associated with this ScheduleAttempt; in fact should not be any, but this
        # is just to be sure
        db.session.query(ScheduleSlot).filter_by(owner_id=record.id).delete()

        expire_time = datetime.now() + timedelta(days=1)
        if record.lp_file is not None:
            record.lp_file.expiry = expire_time
            record.lp_file = None

        db.session.delete(record)
        db.session.commit()

    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            'Can not terminate scheduling task "{name}" due to a database error. ' "Please contact a system administrator.".format(name=record.name),
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@admin.route("/delete_schedule/<int:id>")
@roles_accepted("faculty", "admin", "root")
def delete_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        flash('Can not delete schedule "{name}" because it has not terminated.'.format(name=record.name), "info")
        return redirect(redirect_url())

    if record.deployed:
        flash('Can not delete schedule "{name}" because it has been deployed.'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not current_user.has_role("root") and current_user.id != record.creator_id:
        flash('Schedule "{name}" cannot be deleted because it belongs to another user', "info")
        return redirect(redirect_url())

    title = "Delete schedule"
    panel_title = "Delete schedule <strong>{name}</strong>".format(name=record.name)

    action_url = url_for("admin.perform_delete_schedule", id=id, url=request.referrer)

    if record.published:
        message = (
            "<p>Please confirm that you wish to delete the schedule "
            "<strong>{name}</strong>. Note that this schedule has been "
            "published to project convenors.</p>"
            "<p>This action cannot be undone.</p>".format(name=record.name)
        )
    else:
        message = (
            "<p>Please confirm that you wish to delete the schedule "
            "<strong>{name}</strong>.</p>"
            "<p>This action cannot be undone.</p>".format(name=record.name)
        )

    submit_label = "Delete schedule"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/perform_delete_schedule/<int:id>")
@roles_accepted("faculty", "admin", "root")
def perform_delete_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.assessment_schedules", id=record.owner_id)

    if not validate_schedule_inspector(record):
        return redirect(url)

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        flash('Can not delete schedule "{name}" because it has not terminated.'.format(name=record.name), "info")
        return redirect(url)

    if record.deployed:
        flash('Can not delete schedule "{name}" because it has been deployed.'.format(name=record.name), "info")
        return redirect(url)

    if not current_user.has_role("root") and current_user.id != record.creator_id:
        flash('Schedule "{name}" cannot be deleted because it belongs to another user', "info")
        return redirect(url)

    try:
        # delete all ScheduleSlots associated with this ScheduleAttempt
        for slot in record.slots:
            slot.assessors = []
            slot.talks = []
            db.session.delete(slot)
        db.session.flush()

        expire_time = datetime.now() + timedelta(days=1)
        if record.lp_file is not None:
            record.lp_file.expiry = expire_time
            record.lp_file = None

        db.session.delete(record)
        db.session.commit()

    except SQLAlchemyError as e:
        db.session.rollback()
        flash('Can not delete schedule "{name}" due to a database error. ' "Please contact a system administrator.".format(name=record.name), "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@admin.route("/revert_schedule/<int:id>")
@roles_accepted("faculty", "admin", "root")
def revert_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash('Can not revert schedule "{name}" because it is still awaiting ' "manual upload".format(name=record.name), "error")
        else:
            flash('Can not revert schedule "{name}" because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Can not revert schedule "{name}" because it did not yield a usable outcome.'.format(name=record.name), "error")
        return redirect(redirect_url())

    title = "Revert schedule"
    panel_title = "Revert schedule <strong>{name}</strong>".format(name=record.name)

    action_url = url_for("admin.perform_revert_schedule", id=id, url=request.referrer)
    message = (
        "<p>Please confirm that you wish to revert the schedule "
        "<strong>{name}</strong> to its original state.</p>"
        "<p>This action cannot be undone.</p>".format(name=record.name)
    )
    submit_label = "Revert schedule"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@admin.route("/perform_revert_schedule/<int:id>")
@roles_accepted("faculty", "admin", "root")
def perform_revert_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        # TODO consider an alternative implementation here
        url = url_for("admin.assessment_schedules", id=record.owner_id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash('Can not revert schedule "{name}" because it is still awaiting ' "manual upload".format(name=record.name), "error")
        else:
            flash('Can not revert schedule "{name}" because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Can not revert schedule "{name}" because it did not yield a usable outcome.'.format(name=record.name), "error")
        return redirect(redirect_url())

    # hand off revert job to asynchronous queue
    celery = current_app.extensions["celery"]
    revert = celery.tasks["app.tasks.scheduling.revert"]

    tk_name = "Revert {name}".format(name=record.name)
    tk_description = "Revert schedule to its original state"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(init.si(task_id, tk_name), revert.si(record.id), final.si(task_id, tk_name, current_user.id)).on_error(
        error.si(task_id, tk_name, current_user.id)
    )
    seq.apply_async(task_id=task_id)

    return redirect(url)


@admin.route("/duplicate_schedule/<int:id>")
@roles_accepted("faculty", "admin", "root")
def duplicate_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            if not record.celery_finished:
                flash(
                    'Can not duplicate schedule "{name}" because the files for offline processing '
                    "are still being generated.".format(name=record.name),
                    "error",
                )
                return redirect(redirect_url())
        else:
            flash('Can not duplicate schedule "{name}" because it has not yet terminated.'.format(name=record.name), "error")
            return redirect(redirect_url())

    if record.finished and not record.solution_usable:
        flash('Can not duplicate schedule "{name}" because it did not yield a usable outcome.'.format(name=record.name), "error")
        return redirect(redirect_url())

    suffix = 2
    while suffix < 100:
        new_name = "{name} #{suffix}".format(name=record.name, suffix=suffix)

        if ScheduleAttempt.query.filter_by(name=new_name).first() is None:
            break

        suffix += 1

    if suffix >= 100:
        flash('Can not duplicate schedule "{name}" because a new unique tag could not ' "be generated.".format(name=record.name), "error")
        return redirect(redirect_url())

    # hand off duplicate job to asynchronous queue
    celery = current_app.extensions["celery"]
    duplicate = celery.tasks["app.tasks.scheduling.duplicate"]

    tk_name = "Duplicate {name}".format(name=record.name)
    tk_description = "Duplicate presentation assessment schedule"
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(init.si(task_id, tk_name), duplicate.si(record.id, new_name, current_user.id), final.si(task_id, tk_name, current_user.id)).on_error(
        error.si(task_id, tk_name, current_user.id)
    )
    seq.apply_async(task_id=task_id)

    return redirect(redirect_url())


@admin.route("/rename_schedule/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def rename_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("admin.assessment_schedules", id=record.owner_id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    RenameScheduleForm = RenameScheduleFormFactory(record.owner)
    form = RenameScheduleForm(obj=record)
    form.schedule = record

    if form.validate_on_submit():
        try:
            record.name = form.name.data
            record.tag = form.tag.data
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            flash(
                'Could not rename schedule "{name}" due to a database error. ' "Please contact a system administrator.".format(name=record.name),
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)

    return render_template_context("admin/presentations/scheduling/rename.html", form=form, record=record, url=url)


@admin.route("/compare_schedule/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def compare_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for comparison because it is still awaiting ' "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash('Schedule "{name}" is not yet available for comparison because it has not yet ' "terminated.".format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be used for comparison.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    CompareScheduleForm = CompareScheduleFormFactory(record.owner_id, record.id, current_user.has_role("root"))
    form = CompareScheduleForm(request.form)

    if form.validate_on_submit():
        comparator = form.target.data
        return redirect(url_for("admin.do_schedule_compare", id1=id, id2=comparator.id, text=text, url=url))

    return render_template_context("admin/presentations/schedule_inspector/compare_setup.html", form=form, record=record, text=text, url=url)


@admin.route("/do_schedule_compare/<int:id1>/<int:id2>")
@roles_accepted("faculty", "admin", "root")
def do_schedule_compare(id1, id2):
    record1: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id1)
    record2: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id2)

    pclass_filter = request.args.get("pclass_filter")
    url = request.args.get("url", None)
    text = request.args.get("text", None)

    if url is None:
        url = redirect_url()

    if not validate_schedule_inspector(record1) or not validate_schedule_inspector(record2):
        return redirect(url)

    if record1.owner_id != record2.owner_id:
        flash(
            "It is only possible to compare two schedules belonging to the same assessment. "
            'Schedule "{name1}" belongs to assessment "{assess1}", but schedule '
            '"{name2}" belongs to assessment "{assess2}"'.format(
                name1=record1.name, name2=record2.name, assess1=record1.owner.name, assess2=record2.owner.name
            )
        )
        return redirect(url)

    if not validate_assessment(record1.owner):
        return redirect(url)

    if not record1.finished:
        if record1.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for comparison because it is still awaiting ' "manual upload.".format(name=record1.name),
                "error",
            )
        else:
            flash('Schedule "{name}" is not yet available for comparison because it has not yet ' "terminated.".format(name=record1.name), "error")
        return redirect(url)

    if not record1.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be used for comparison.".format(name=record1.name),
            "info",
        )
        return redirect(url)

    if not record2.finished:
        if record2.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for comparison because it is still awaiting ' "manual upload.".format(name=record2.name),
                "error",
            )
        else:
            flash('Schedule "{name}" is not yet available for comparison because it has not yet ' "terminated.".format(name=record2.name), "error")
        return redirect(url)

    if not record2.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be used for comparison.".format(name=record2.name),
            "info",
        )
        return redirect(url)

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get("admin_schedule_pclass_filter"):
        pclass_filter = session["admin_schedule_pclass_filter"]

    pclasses = record1.available_pclasses

    return render_template_context(
        "admin/presentations/schedule_inspector/compare.html",
        record1=record1,
        record2=record2,
        text=text,
        url=url,
        pclasses=pclasses,
        pclass_filter=pclass_filter,
    )


@admin.route("/do_schedule_compare_ajax/<int:id1>/<int:id2>")
@roles_accepted("faculty", "admin", "root")
def do_schedule_compare_ajax(id1, id2):
    record1: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id1)
    record2: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id2)

    if not validate_schedule_inspector(record1) or not validate_schedule_inspector(record2):
        return jsonify({})

    if record1.owner_id != record2.owner_id:
        flash(
            "It is only possible to compare two schedules belonging to the same assessment. "
            'Schedule "{name1}" belongs to assessment "{assess1}", but schedule '
            '"{name2}" belongs to assessment "{assess2}"'.format(
                name1=record1.name, name2=record2.name, assess1=record1.owner.name, assess2=record2.owner.name
            )
        )
        return jsonify({})

    if not validate_assessment(record1.owner):
        return jsonify({})

    if not record1.finished:
        if record1.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for comparison because it is still awaiting ' "manual upload.".format(name=record1.name),
                "error",
            )
        else:
            flash('Schedule "{name}" is not yet available for comparison because it has not yet ' "terminated.".format(name=record1.name), "error")
        return jsonify({})

    if not record1.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be used for comparison.".format(name=record1.name),
            "info",
        )
        return jsonify({})

    if not record2.finished:
        if record2.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for comparison because it is still awaiting ' "manual upload.".format(name=record2.name),
                "error",
            )
        else:
            flash('Schedule "{name}" is not yet available for comparison because it has not yet ' "terminated.".format(name=record2.name), "error")
        return jsonify({})

    if not record2.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be used for comparison.".format(name=record2.name),
            "info",
        )
        return jsonify({})

    pclass_filter = request.args.get("pclass_filter")
    flag, pclass_value = is_integer(pclass_filter)

    pairs = pair_slots(record1.ordered_slots, record2.ordered_slots, flag, pclass_value)

    return ajax.admin.compare_schedule_data(pairs, record1.id, record2.id)


@admin.route("/publish_schedule/<int:id>")
@roles_required("root")
def publish_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for publication because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash('Schedule "{name}" is not yet available for publication because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be shared with convenors.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    if record.deployed:
        flash('Schedule "{name}" is deployed and is not available to be published.'.format(name=record.name), "info")
        return redirect(redirect_url())

    record.published = True
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/unpublish_schedule/<int:id>")
@roles_required("root")
def unpublish_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for unpublication because it is still awaiting ' "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash('Schedule "{name}" is not yet available for unpublication because it has not yet ' "terminated.".format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be shared with convenors.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    record.published = False
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/publish_schedule_submitters/<int:id>")
@roles_required("root")
def publish_schedule_submitters(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for sharing with submitters because it is still awaiting '
                "manual upload.".format(name=record.name),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" is not yet available for sharing with submitters because it has not yet ' "terminated.".format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be shared by email.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    task_id = register_task(
        "Send schedule to submitters", owner=current_user, description='Email details of schedule "{name}" to submitters'.format(name=record.name)
    )

    celery = current_app.extensions["celery"]
    task = celery.tasks["app.tasks.scheduling.publish_to_submitters"]

    task.apply_async(args=(id, current_user.id, task_id), task_id=task_id)

    return redirect(redirect_url())


@admin.route("/publish_schedule_assessors/<int:id>")
@roles_required("root")
def publish_schedule_assessors(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for sharing with assessors because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" is not yet available for sharing with assessors because it has not yet terminated.'.format(name=record.name),
                "error",
            )
        return redirect(redirect_url())

    if not record.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be shared by email.".format(name=record.name),
            "info",
        )
        return redirect(redirect_url())

    task_id = register_task(
        "Send draft schedule to assessors", owner=current_user, description='Email details of schedule "{name}" to assessors'.format(name=record.name)
    )

    celery = current_app.extensions["celery"]
    task = celery.tasks["app.tasks.scheduling.publish_to_assessors"]

    task.apply_async(args=(id, current_user.id, task_id), task_id=task_id)

    return redirect(redirect_url())


@admin.route("/deploy_schedule/<int:id>")
@roles_required("root")
def deploy_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if record.owner.is_deployed:
        flash(
            'The assessment "{name}" already has a deployed schedule. Only one schedule can be deployed at a time.'.format(name=record.owner.name),
            "info",
        )

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for deployment because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash('Schedule "{name}" is not yet available for deployment because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Schedule "{name}" did not yield an optimal solution and is not available for deployment.'.format(name=record.name), "info")
        return redirect(redirect_url())

    record.deployed = True
    record.published = False
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/undeploy_schedule/<int:id>")
@roles_required("root")
def undeploy_schedule(id):
    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for undeployment because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash('Schedule "{name}" is not yet available for undeployment because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Schedule "{name}" did not yield an optimal solution and is not available for deployment.'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not record.is_revokable:
        flash(
            'Schedule "{name}" is not revokable. This may be because some scheduled slots are in '
            "the past, or because some feedback has already been entered.".format(name=record.name),
            "error",
        )

    record.deployed = False
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/schedule_view_sessions/<int:id>")
@roles_accepted("faculty", "admin", "root")
def schedule_view_sessions(id):
    """
    Sessions view in schedule inspector
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for inspection because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash('Schedule "{name}" is not yet available for inspection because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Schedule "{name}" is not available for inspection because it did not yield an optimal solution.'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    building_filter, pclass_filter, room_filter, session_filter = _store_schedule_filters()

    pclasses = record.available_pclasses
    buildings = record.available_buildings
    rooms = record.available_rooms
    sessions = record.available_sessions

    return render_template_context(
        "admin/presentations/schedule_inspector/sessions.html",
        pane="sessions",
        record=record,
        pclasses=pclasses,
        buildings=buildings,
        rooms=rooms,
        sessions=sessions,
        pclass_filter=pclass_filter,
        building_filter=building_filter,
        room_filter=room_filter,
        session_filter=session_filter,
        text=text,
        url=url,
    )


@admin.route("/schedule_view_faculty/<int:id>")
@roles_accepted("faculty", "admin", "root")
def schedule_view_faculty(id):
    """
    Faculty view in schedule inspector
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for inspection because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash('Schedule "{name}" is not yet available for inspection because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Schedule "{name}" is not available for inspection because it did not yield an optimal solution.'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    building_filter, pclass_filter, room_filter, session_filter = _store_schedule_filters()

    pclasses = record.available_pclasses
    buildings = record.available_buildings
    rooms = record.available_rooms
    sessions = record.available_sessions

    return render_template_context(
        "admin/presentations/schedule_inspector/faculty.html",
        pane="faculty",
        record=record,
        pclasses=pclasses,
        buildings=buildings,
        rooms=rooms,
        sessions=sessions,
        pclass_filter=pclass_filter,
        building_filter=building_filter,
        room_filter=room_filter,
        session_filter=session_filter,
        text=text,
        url=url,
    )


def _store_schedule_filters():
    pclass_filter = request.args.get("pclass_filter")
    building_filter = request.args.get("building_filter")
    room_filter = request.args.get("room_filter")
    session_filter = request.args.get("session_filter")

    # if no state filter supplied, check if one is stored in session
    if pclass_filter is None and session.get("admin_pclass_filter"):
        pclass_filter = session["admin_pclass_filter"]

    if pclass_filter is not None:
        session["admin_pclass_filter"] = pclass_filter

    if building_filter is None and session.get("admin_building_filter"):
        building_filter = session["admin_building_filter"]

    if building_filter is not None:
        session["admin_building_filter"] = building_filter

    if room_filter is None and session.get("admin_room_filter"):
        building_filter = session["admin_room_filter"]

    if room_filter is not None:
        session["admin_room_filter"] = room_filter

    if session_filter is None and session.get("admin_session_filter"):
        session_filter = session["admin_session_filter"]

    if session_filter is not None:
        session["admin_session_filter"] = session_filter

    return building_filter, pclass_filter, room_filter, session_filter


@admin.route("/schedule_view_sessions_ajax/<int:id>")
@roles_accepted("faculty", "admin", "root")
def schedule_view_sessions_ajax(id):
    """
    AJAX data point for Sessions view in Schedule inspector
    """
    if not validate_using_assessment():
        return jsonify({})

    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_assessment(record.owner):
        return jsonify({})

    if not record.finished:
        return jsonify({})

    if not record.solution_usable:
        return jsonify({})

    if not validate_schedule_inspector(record):
        return jsonify({})

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    pclass_filter = request.args.get("pclass_filter")
    building_filter = request.args.get("building_filter")
    room_filter = request.args.get("room_filter")
    session_filter = request.args.get("session_filter")

    # now want to extract all slots from 'record' that satisfy the filters
    slots = record.slots
    joined_room = False

    flag, session_value = is_integer(session_filter)
    if flag:
        slots = slots.filter_by(session_id=session_value)

    flag, building_value = is_integer(building_filter)
    if flag:
        slots = slots.join(Room, Room.id == ScheduleSlot.room_id).filter(Room.building_id == building_value)
        joined_room = True

    flag, room_value = is_integer(room_filter)
    if flag:
        if not joined_room:
            slots = slots.join(Room, Room.id == ScheduleSlot.room_id)
        slots = slots.filter(Room.id == room_value)

    flag, pclass_value = is_integer(pclass_filter)
    if flag:
        slots = [t for t in slots.all() if t.has_pclass(pclass_value)]
    else:
        slots = slots.all()

    return ajax.admin.schedule_view_sessions(slots, record, url=url, text=text)


@admin.route("/schedule_view_faculty_ajax/<int:id>")
@roles_accepted("faculty", "admin", "root")
def schedule_view_faculty_ajax(id):
    """
    AJAX data point for Faculty view in Schedule inspector
    """
    if not validate_using_assessment():
        return jsonify({})

    record: ScheduleAttempt = ScheduleAttempt.query.get_or_404(id)

    if not validate_assessment(record.owner):
        return jsonify({})

    if not record.finished:
        return jsonify({})

    if not record.solution_usable:
        return jsonify({})

    if not validate_schedule_inspector(record):
        return jsonify({})

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    pclass_filter = request.args.get("pclass_filter")
    building_filter = request.args.get("building_filter")
    room_filter = request.args.get("room_filter")
    session_filter = request.args.get("session_filter")

    assessors = []
    for assessor in record.owner.ordered_assessors:
        slots = record.get_faculty_slots(assessor.faculty.id)
        joined_room = False

        flag, session_value = is_integer(session_filter)
        if flag:
            slots = slots.filter_by(session_id=session_value)

        flag, building_value = is_integer(building_filter)
        if flag:
            slots = slots.join(Room, Room.id == ScheduleSlot.room_id).filter(Room.building_id == building_value)
            joined_room = True

        flag, room_value = is_integer(room_filter)
        if flag:
            if not joined_room:
                slots = slots.join(Room, Room.id == ScheduleSlot.room_id)
            slots = slots.filter(Room.id == room_value)

        flag, pclass_value = is_integer(pclass_filter)
        if flag:
            slots = [t for t in slots.all() if t.has_pclass(pclass_value)]
        else:
            slots = slots.all()

        assessors.append((assessor, slots))

    return ajax.admin.schedule_view_faculty(assessors, record, url=url, text=text)


@admin.route("/schedule_adjust_assessors/<int:id>")
@roles_accepted("root", "admin", "faculty")
def schedule_adjust_assessors(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    slot: ScheduleSlot = ScheduleSlot.query.get_or_404(id)
    record: ScheduleAttempt = slot.owner  # = ScheduleAttempt

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for inspection because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash('Schedule "{name}" is not yet available for inspection because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Schedule "{name}" is not available for inspection because it did not yield an optimal solution.'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    return render_template_context("admin/presentations/schedule_inspector/assign_assessors.html", url=url, text=text, slot=slot, rec=record)


@admin.route("/schedule_assign_assessors_ajax/<int:id>")
@roles_accepted("root", "admin", "faculty")
def schedule_assign_assessors_ajax(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    slot: ScheduleSlot = ScheduleSlot.query.get_or_404(id)
    record: ScheduleAttempt = slot.owner  # = ScheduleAttempt

    if not validate_assessment(record.owner):
        return jsonify({})

    if not record.finished:
        return jsonify({})

    if not record.solution_usable:
        return jsonify({})

    if not validate_schedule_inspector(record):
        return jsonify({})

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    candidates = []
    pclass: ProjectClass = slot.pclass

    for item in record.owner.ordered_assessors:
        # candidate assessors should be available in this slot
        if slot.session.faculty_available(item.faculty_id) or slot.session.faculty_ifneeded(item.faculty_id):
            is_candidate = True

            if pclass is not None:
                # assessors should also be enrolled for the project class corresponding to this slot
                enrolment = item.faculty.get_enrollment_record(pclass.id)
                available = enrolment is not None and enrolment.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED

                if not available:
                    is_candidate = False

            # check whether this faculty has any existing assignments in this session
            num_existing = get_count(
                db.session.query(ScheduleSlot).filter(
                    ScheduleSlot.owner_id == record.id, ScheduleSlot.session_id == slot.session_id, ScheduleSlot.assessors.any(id=item.faculty_id)
                )
            )

            # if not, can offer them as a candidate
            if num_existing > 0:
                is_candidate = False

            if is_candidate:
                slots = record.get_faculty_slots(item.faculty_id).all()
                candidates.append((item, slots))

    return ajax.admin.assign_assessor_data(candidates, slot, url=url, text=text)


@admin.route("/schedule_adjust_assessors/<int:slot_id>/<int:fac_id>")
@roles_accepted("root", "admin", "faculty")
def schedule_attach_assessor(slot_id, fac_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    slot: ScheduleSlot = ScheduleSlot.query.get_or_404(slot_id)
    record: ScheduleAttempt = slot.owner  # = ScheduleAttempt

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for inspection because it is still awaiting manual upload.'.format(name=record.name),
                "error",
            )
        else:
            flash('Schedule "{name}" is not yet available for inspection because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Schedule "{name}" is not available for inspection because it did not yield an optimal solution.'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not record.owner.includes_faculty(fac_id):
        flash("The specified faculty member is not attached to this assessment", "error")
        return redirect(redirect_url())

    item = record.owner.assessors_query.filter(AssessorAttendanceData.faculty_id == fac_id).first()

    if item is None:
        flash("Could not attach this faculty member due to a database error", "error")
        return redirect(redirect_url())

    if get_count(slot.assessors.filter_by(id=item.faculty_id)) == 0:
        slot.assessors.append(item.faculty)

        record.last_edit_id = current_user.id
        record.last_edit_timestamp = datetime.now()

        db.session.commit()

    return redirect(redirect_url())


@admin.route("/schedule_remove_assessors/<int:slot_id>/<int:fac_id>")
@roles_accepted("root", "admin", "faculty")
def schedule_remove_assessor(slot_id, fac_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    slot: ScheduleSlot = ScheduleSlot.query.get_or_404(slot_id)
    record: ScheduleAttempt = slot.owner  # = ScheduleAttempt

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash('Schedule "{name}" cannot yet be adjusted because it is still awaiting manual upload.'.format(name=record.name), "error")
        else:
            flash('Schedule "{name}" cannot yet be adjusted because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Schedule "{name}" cannot yet be adjusted because it did not yield an optimal solution.'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    if not record.owner.includes_faculty(fac_id):
        flash("The specified faculty member is not attached to this assessment", "error")
        return redirect(redirect_url())

    item = record.owner.assessors_query.filter(AssessorAttendanceData.faculty_id == fac_id).first()

    if item is None:
        flash("Could not attach this faculty member due to a database error", "error")
        return redirect(redirect_url())

    if get_count(slot.assessors.filter_by(id=item.faculty_id)) > 0:
        slot.assessors.remove(item.faculty)

        record.last_edit_id = current_user.id
        record.last_edit_timestamp = datetime.now()

        db.session.commit()

    return redirect(redirect_url())


@admin.route("/schedule_adjust_submitter/<int:slot_id>/<int:talk_id>")
@roles_accepted("root", "admin", "faculty")
def schedule_adjust_submitter(slot_id, talk_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    slot: ScheduleSlot = ScheduleSlot.query.get_or_404(slot_id)
    record: ScheduleAttempt = slot.owner  # = ScheduleAttempt

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash('Schedule "{name}" cannot yet be adjusted because it is still awaiting manual upload.'.format(name=record.name), "error")
        else:
            flash('Schedule "{name}" cannot yet be adjusted because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Schedule "{name}" cannot yet be adjusted because it did not yield an optimal solution.'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    talk = SubmissionRecord.query.get_or_404(talk_id)

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    return render_template_context(
        "admin/presentations/schedule_inspector/assign_presentation.html", url=url, text=text, slot=slot, rec=record, talk=talk
    )


@admin.route("/schedule_assign_submitter_ajax/<int:slot_id>/<int:talk_id>")
@roles_accepted("root", "admin", "faculty")
def schedule_assign_submitter_ajax(slot_id, talk_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    slot: ScheduleSlot = ScheduleSlot.query.get_or_404(slot_id)
    record: ScheduleAttempt = slot.owner  # = ScheduleAttempt

    if not validate_assessment(record.owner):
        return jsonify({})

    if not record.finished:
        return jsonify({})

    if not record.solution_usable:
        return jsonify({})

    if not validate_schedule_inspector(record):
        return jsonify({})

    talk = SubmissionRecord.query.get_or_404(talk_id)

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    pclass = slot.pclass

    def check_valid(s):
        if s.pclass is not None and pclass is not None:
            if s.pclass.id != pclass.id:
                return False

        return s.session.submitter_available(talk.id) and s.id != slot.id

    slots = [s for s in record.slots.all() if check_valid(s)]

    return ajax.admin.assign_submitter_data(slots, slot, talk, url=url, text=text)


@admin.route("/schedule_move_submitter/<int:old_id>/<int:new_id>/<int:talk_id>")
@roles_accepted("root", "admin", "faculty")
def schedule_move_submitter(old_id, new_id, talk_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    old_slot: ScheduleSlot = ScheduleSlot.query.get_or_404(old_id)
    new_slot: ScheduleSlot = ScheduleSlot.query.get_or_404(new_id)
    record: ScheduleAttempt = old_slot.owner  # = ScheduleAttempt

    if old_slot.owner_id != new_slot.owner_id:
        flash("Cannot move specified talk because destination slot does not belong to the same ScheduleAttempt instance.", "error")
        return redirect(redirect_url())

    if not validate_assessment(record.owner):
        return redirect(redirect_url())

    if not record.finished:
        if record.awaiting_upload:
            flash('Schedule "{name}" cannot yet be adjusted because it is still awaiting manual upload.'.format(name=record.name), "error")
        else:
            flash('Schedule "{name}" cannot yet be adjusted because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Schedule "{name}" cannot yet be adjusted because it did not yield an optimal solution.'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    talk = SubmissionRecord.query.get_or_404(talk_id)

    if not record.owner.includes_submitter(talk.id):
        flash("The specified submitting student is not attached to this assessment", "error")
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    if get_count(old_slot.talks.filter_by(id=talk.id)) > 0:
        old_slot.talks.remove(talk)

    if get_count(new_slot.talks.filter_by(id=talk.id)) == 0:
        new_slot.talks.append(talk)

    record.last_edit_id = current_user.id
    record.last_edit_timestamp = datetime.now()

    db.session.commit()

    return redirect(url_for("admin.schedule_adjust_submitter", slot_id=new_id, talk_id=talk_id, url=url, text=text))


@admin.route("/schedule_move_room/<int:slot_id>/<int:room_id>")
@roles_accepted("root", "admin", "faculty")
def schedule_move_room(slot_id, room_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    slot: ScheduleSlot = ScheduleSlot.query.get_or_404(slot_id)
    room: Room = Room.query.get_or_404(room_id)

    record = slot.owner

    if not record.finished:
        if record.awaiting_upload:
            flash('Schedule "{name}" cannot yet be adjusted because it is still awaiting manual upload.'.format(name=record.name), "error")
        else:
            flash('Schedule "{name}" cannot yet be adjusted because it has not yet terminated.'.format(name=record.name), "error")
        return redirect(redirect_url())

    if not record.solution_usable:
        flash('Schedule "{name}" cannot yet be adjusted because it did not yield an optimal solution.'.format(name=record.name), "info")
        return redirect(redirect_url())

    if not validate_schedule_inspector(record):
        return redirect(redirect_url())

    available_rooms = slot.alternative_rooms
    if room in available_rooms:
        slot.room_id = room.id
        db.session.commit()

    else:
        flash(
            'Cannot assign venue "{room}" to this slot because it is unavailable, or does not meet '
            "the required criteria.".format(room=room.full_name)
        )

    return redirect(redirect_url())


@admin.route("/assessment_manage_attendees/<int:id>")
@roles_required("root")
def assessment_manage_attendees(id):
    """
    Manage student attendees for an existing assessment event
    :param id:
    :return:
    """
    if not validate_using_assessment():
        return redirect(redirect_url())

    data: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    if not validate_assessment(data):
        return redirect(redirect_url())

    pclass_filter = request.args.get("pclass_filter")

    if pclass_filter is None and session.get("attendees_pclass_filter"):
        pclass_filter = session["attendees_pclass_filter"]

    if pclass_filter is not None:
        session["attendees_pclass_filter"] = pclass_filter

    attend_filter = request.args.get("attend_filter")

    if attend_filter is None and session.get("attendees_attend_filter"):
        attend_filter = session["attendees_attend_filter"]

    if attend_filter is not None:
        session["attendees_attend_filter"] = attend_filter

    pclasses = data.available_pclasses

    return render_template_context(
        "admin/presentations/manage_attendees.html", assessment=data, pclass_filter=pclass_filter, attend_filter=attend_filter, pclasses=pclasses
    )


@admin.route("/merge_change_schedule/<int:source_id>/<int:target_id>/<int:source_sched>/<int:target_sched>")
@roles_accepted("root", "faculty", "admin")
def merge_change_schedule(source_id, target_id, source_sched, target_sched):
    """
    Makes target into a copy of source
    :param source_id:
    :param target_id:
    :return:
    """
    if source_id is not None:
        source = ScheduleSlot.query.get_or_404(source_id)
    else:
        source = None

    if target_id is not None:
        target = ScheduleSlot.query.get_or_404(target_id)
    else:
        target = None

    source_schedule = ScheduleAttempt.query.get_or_404(source_sched)
    target_schedule = ScheduleAttempt.query.get_or_404(target_sched)

    if not validate_schedule_inspector(source_schedule) or not validate_schedule_inspector(target_schedule):
        return redirect(redirect_url())

    # check that source and target schedules are owned by the same assessent
    if source_schedule.owner_id != target_schedule.owner_id:
        flash(
            "It is only possible to merge two schedules belonging to the same assessment. "
            'Schedule "{name1}" belongs to assessment "{assess1}", but schedule '
            '"{name2}" belongs to assessment "{assess2}"'.format(
                name1=source_schedule.name, name2=target_schedule.name, assess1=source_schedule.owner.name, assess2=target_schedule.owner.name
            )
        )
        return redirect(redirect_url())

    if not validate_assessment(source_schedule.owner):
        return redirect(redirect_url())

    if not source_schedule.finished:
        if source_schedule.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for merging because it is still awaiting manual upload.'.format(name=source_schedule.name),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" is not yet available for merging because it has not yet terminated.'.format(name=source_schedule.name), "error"
            )
        return redirect(redirect_url())

    if not source_schedule.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be used for merging.".format(name=source_schedule.name),
            "info",
        )
        return redirect(redirect_url())

    if target_schedule is not None and not target_schedule.finished:
        if target_schedule.awaiting_upload:
            flash(
                'Schedule "{name}" is not yet available for merging because it is still awaiting manual upload.'.format(name=target_schedule.name),
                "error",
            )
        else:
            flash(
                'Schedule "{name}" is not yet available for merging because it has not yet terminated.'.format(name=target_schedule.name), "error"
            )
        return redirect(redirect_url())

    if target_schedule is not None and not target_schedule.solution_usable:
        flash(
            'Schedule "{name}" did not yield an optimal solution and is not available for use. '
            "It cannot be used for merging.".format(name=target_schedule.name),
            "info",
        )
        return redirect(redirect_url())

    if source is None and target is not None:
        # remove target session
        db.session.delete(target)

    elif target is None and source is not None:
        # find first free occupancy label for this room in the target schedule
        max_label = (
            db.session.query(func.max(ScheduleSlot.occupancy_label))
            .filter_by(owner_id=target_schedule.id, session_id=source.session_id, room_id=source.room_id)
            .scalar()
        )

        if max_label is None:
            slot_label = 1
        else:
            slot_label = int(max_label) + 1

        # create new target slot
        data = ScheduleSlot(
            owner_id=target_schedule.id,
            session_id=source.session_id,
            room_id=source.room_id,
            assessors=source.assessors,
            talks=source.talks,
            occupancy_label=slot_label,
            original_assessors=source.original_assessors,
            original_talks=source.original_talks,
        )
        db.session.add(data)

    else:
        target.session_id = source.session_id
        target.room_id = source.room_id
        target.assessors = source.assessors
        target.talks = source.talks

    target_schedule.last_edit_id = current_user.id
    target_schedule.last_edit_timestamp = datetime.now()

    db.session.commit()

    return redirect(redirect_url())


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
        flash("No buildings are available. Set up at least one active building before adding a room.", "error")
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
        db.session.commit()

        return redirect(url_for("admin.edit_rooms"))

    return render_template_context("admin/presentations/edit_room.html", form=form, title="Add new venue")


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

        db.session.commit()

        return redirect(url_for("admin.edit_rooms"))

    return render_template_context("admin/presentations/edit_room.html", form=form, room=data, title="Edit venue")


@admin.route("/activate_room/<int:id>")
@roles_required("root")
def activate_room(id):
    # id is a Room
    data = Room.query.get_or_404(id)

    data.enable()
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/deactivate_room/<int:id>")
@roles_required("root")
def deactivate_room(id):
    # id is a Room
    data = Room.query.get_or_404(id)

    data.disable()
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/edit_buildings")
@roles_required("root")
def edit_buildings():
    """
    Manage list of buildings to which bookable venues can belong.
    Essentially used to identify rooms in the same building with a coloured tag.
    :return:
    """
    return render_template_context("admin/presentations/edit_buildings.html", pane="buildings")


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
        data = Building(name=form.name.data, colour=form.colour.data, active=True, creator_id=current_user.id, creation_timestamp=datetime.now())

        db.session.add(data)
        db.session.commit()

        return redirect(url_for("admin.edit_buildings"))

    return render_template_context("admin/presentations/edit_building.html", form=form, title="Add new building")


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

        db.session.commit()

        return redirect(url_for("admin.edit_buildings"))

    return render_template_context("admin/presentations/edit_building.html", form=form, building=data, title="Edit building")


@admin.route("/activate_building/<int:id>")
@roles_required("root")
def activate_building(id):
    # id is a Building
    data = Building.query.get_or_404(id)

    data.enable()
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/deactivate_building/<int:id>")
@roles_required("root")
def deactivate_building(id):
    # id is a Building
    data = Building.query.get_or_404(id)

    data.disable()
    db.session.commit()

    return redirect(redirect_url())


@admin.route("/launch_test_task")
@roles_required("root")
def launch_test_task():
    task_id = register_task("Test task", owner=current_user, description="Long-running test task")

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

    current_app.logger.info("{real} used superuser powers to log in as alternative user {fake}".format(real=current_user.name, fake=user.name))

    login_user(user, remember=False)
    # don't commit changes to database to avoid confusing this with a real login

    return home_dashboard()


@admin.route("/download_generated_asset/<int:asset_id>")
@login_required
def download_generated_asset(asset_id):
    # asset_is is a GeneratedAsset
    asset = GeneratedAsset.query.get_or_404(asset_id)

    if not asset.has_access(current_user.id):
        flash("You do not have permissions to download this asset. If you think this is a mistake, please contact a system administrator.", "info")
        return redirect(redirect_url())

    filename = request.args.get("filename", None)

    BUCKET_MAP = {
        buckets.ASSETS_BUCKET: current_app.config.get("OBJECT_STORAGE_ASSETS"),
        buckets.BACKUP_BUCKET: current_app.config.get("OBJECT_STORAGE_BACKUP"),
        buckets.INITDB_BUCKET: current_app.config.get("OBJECT_STORAGE_INITDB"),
        buckets.TELEMETRY_BUCKET: current_app.config.get("OBJECT_STORAGE_TELEMETRY"),
        buckets.FEEDBACK_BUCKET: current_app.config.get("OBJECT_STORAGE_FEEDBACK"),
        buckets.PROJECT_BUCKET: current_app.config.get("OBJECT_STORAGE_PROJECT"),
    }

    if asset.bucket not in BUCKET_MAP:
        flash(
            f"This object is stored in a bucket (type={asset.bucket}) which is not part of the configured storage. "
            f"Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    # log this download
    record = GeneratedAssetDownloadRecord(asset_id=asset.id, downloader_id=current_user.id, timestamp=datetime.now())

    try:
        db.session.add(record)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not serve download request for asset_id={number} because of a database error. "
            "Please contact a system administrator".format(number=asset_id),
            "error",
        )
        return redirect(redirect_url())

    object_store = BUCKET_MAP[asset.bucket]
    storage = AssetCloudAdapter(asset, object_store, audit_data=f"download_generated_asset (asset id #{asset_id})")
    return_data = BytesIO()
    with storage.download_to_scratch() as scratch_path:
        file_path = scratch_path.path

        with open(file_path, "rb") as f:
            return_data.write(f.read())
        return_data.seek(0)

    return send_file(return_data, mimetype=asset.mimetype, download_name=filename if filename else asset.target_name, as_attachment=True)


@admin.route("/download_submitted_asset/<int:asset_id>")
@login_required
def download_submitted_asset(asset_id):
    # asset_is is a SubmittedAsset
    asset: SubmittedAsset = SubmittedAsset.query.get_or_404(asset_id)

    sub_attachment: SubmissionAttachment = asset.submission_attachment
    period_attachment: PeriodAttachment = asset.period_attachment

    attachment = sub_attachment if sub_attachment is not None else period_attachment if period_attachment is not None else None

    # attachment may be 'None' if this is an asset that does not have a specific attachment record, e.g., the
    # unprocessed report is usually of this type

    # if an attachment record is available, check its 'publish_to_students' flag
    if attachment is not None:
        if current_user.has_role("student") and not attachment.publish_to_students:
            # give no indication that this asset actually exists
            abort(404)

    if not asset.has_access(current_user.id):
        flash("You do not have permissions to download this asset. If you think this is a mistake, please contact a system administrator.", "info")
        return redirect(redirect_url())

    filename = request.args.get("filename", None)

    BUCKET_MAP = {
        buckets.ASSETS_BUCKET: current_app.config.get("OBJECT_STORAGE_ASSETS"),
        buckets.BACKUP_BUCKET: current_app.config.get("OBJECT_STORAGE_BACKUP"),
        buckets.INITDB_BUCKET: current_app.config.get("OBJECT_STORAGE_INITDB"),
        buckets.TELEMETRY_BUCKET: current_app.config.get("OBJECT_STORAGE_TELEMETRY"),
        buckets.FEEDBACK_BUCKET: current_app.config.get("OBJECT_STORAGE_FEEDBACK"),
        buckets.PROJECT_BUCKET: current_app.config.get("OBJECT_STORAGE_PROJECT"),
    }

    if asset.bucket not in BUCKET_MAP:
        flash(
            f"This object is stored in a bucket (type={asset.bucket}) which is not part of the configured storage. "
            f"Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    # log this download
    record = SubmittedAssetDownloadRecord(asset_id=asset.id, downloader_id=current_user.id, timestamp=datetime.now())

    try:
        db.session.add(record)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not serve download request for asset_id={number} because of a database error. "
            "Please contact a system administrator".format(number=asset_id),
            "error",
        )
        return redirect(redirect_url())

    object_store = BUCKET_MAP[asset.bucket]
    storage = AssetCloudAdapter(asset, current_app.config["OBJECT_STORAGE_ASSETS"], audit_data=f"download_submitted_asset (asset id #{asset_id})")
    return_data = BytesIO()
    with storage.download_to_scratch() as scratch_path:
        file_path = scratch_path.path

        with open(file_path, "rb") as f:
            return_data.write(f.read())
        return_data.seek(0)

    return send_file(return_data, mimetype=asset.mimetype, download_name=filename if filename else asset.target_name, as_attachment=True)


@admin.route("/download_backup/<int:backup_id>")
@roles_required("root")
def download_backup(backup_id):
    # backup_id is a BackupRecord instance
    backup: BackupRecord = BackupRecord.query.get_or_404(backup_id)

    filename = request.args.get("filename", None)

    storage = AssetCloudAdapter(
        backup, current_app.config["OBJECT_STORAGE_BACKUP"], audit_data=f"download_backup (backup id #{backup_id})", size_attr="archive_size"
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
    return send_file(return_data, mimetype="application/gzip", download_name=str(fname), as_attachment=True)


@admin.route("/lock_backup/<int:backup_id>")
@roles_required("root")
def lock_backup(backup_id):
    # backup_id is a BackupRecord instance
    backup: BackupRecord = BackupRecord.query.get_or_404(backup_id)

    try:
        backup.locked = True
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not lock this backup because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@admin.route("/unlock_backup/<int:backup_id>")
@roles_required("root")
def unlock_backup(backup_id):
    # backup_id is a BackupRecord instance
    backup: BackupRecord = BackupRecord.query.get_or_404(backup_id)

    try:
        backup.locked = False
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not lock this backup because of a database error. Please contact a system administrator", "error")

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
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemy exception", exc_info=e)
            flash("Could not save labels for this backup record due to a database error. Please contact a system administrator", "error")

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
                    form.solver.data == ScheduleAttempt.SOLVER_CBC_PACKAGED or form.solver.data == ScheduleAttempt.SOLVER_CBC_CMD
                ) and extension not in (".lp",):
                    flash("Solution files for the CBC optimizer must be in .LP format", "error")

                else:
                    now = datetime.now()
                    asset = TemporaryAsset(timestamp=now, expiry=now + timedelta(days=1))

                    object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
                    with AssetUploadManager(
                        asset,
                        data=sol_file.stream.read(),
                        storage=object_store,
                        audit_data=f"upload_schedule (schedule id #{schedule_id})",
                        length=sol_file.content_length,
                        validate_nonce=validate_nonce,
                    ) as upload_mgr:
                        pass

                    asset.grant_user(current_user)

                    uuid = register_task(
                        'Process offline solution for "{name}"'.format(name=record.name),
                        owner=current_user,
                        description="Import a solution file that has been produced offline and convert to a schedule",
                    )

                    # update solver information from form
                    record.solver = form.solver.data
                    record.celery_finished = False
                    record.celery_id = uuid

                    try:
                        db.session.add(asset)
                        db.session.commit()
                    except SQLAlchemyError as e:
                        db.session.rollback()
                        flash("Could not upload offline solution due to a database issue. Please contact an administrator.", "error")
                        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                        return redirect(url_for("admin.assessment_schedules", id=record.owner_id))

                    celery = current_app.extensions["celery"]
                    schedule_task = celery.tasks["app.tasks.scheduling.process_offline_solution"]

                    schedule_task.apply_async(args=(record.id, asset.id, current_user.id), task_id=uuid)

                    return redirect(url_for("admin.assessment_schedules", id=record.owner_id))

            else:
                flash("Optimizer solution files should have extension .sol or .mps.", "error")

    else:
        if request.method == "GET":
            form.solver.data = record.solver

    return render_template_context("admin/presentations/scheduling/upload.html", schedule=record, form=form)


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
                    form.solver.data == ScheduleAttempt.SOLVER_CBC_PACKAGED or form.solver.data == ScheduleAttempt.SOLVER_CBC_CMD
                ) and extension not in (".lp",):
                    flash("Solution files for the CBC optimizer must be in .LP format", "error")

                else:
                    now = datetime.now()
                    asset = TemporaryAsset(timestamp=now, expiry=now + timedelta(days=1))

                    object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
                    with AssetUploadManager(
                        asset,
                        data=sol_file.stream.read(),
                        storage=object_store,
                        audit_data=f"upload_match (match id #{match_id})",
                        length=sol_file.content_length,
                        validate_nonce=validate_nonce,
                    ) as upload_mgr:
                        pass

                    asset.grant_user(current_user)

                    uuid = register_task(
                        'Process offline solution for "{name}"'.format(name=record.name),
                        owner=current_user,
                        description="Import a solution file that has been produced offline and convert to a project match",
                    )

                    # update solver information from form
                    record.solver = form.solver.data
                    record.celery_finished = False
                    record.celery_id = uuid

                    try:
                        db.session.add(asset)
                        db.session.commit()
                    except SQLAlchemyError as e:
                        db.session.rollback()
                        flash("Could not upload offline solution due to a database issue. Please contact an administrator.", "error")
                        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                        return redirect(url_for("admin.manage_matching"))

                    celery = current_app.extensions["celery"]
                    schedule_task = celery.tasks["app.tasks.matching.process_offline_solution"]

                    schedule_task.apply_async(args=(record.id, asset.id, current_user.id), task_id=uuid)

                    return redirect(url_for("admin.manage_matching"))

            else:
                flash("Optimizer solution files should have extension .sol or .mps.", "error")

    else:
        if request.method == "GET":
            form.solver.data = record.solver

    return render_template_context("admin/matching/upload.html", match=record, form=form)


@admin.route("/view_schedule/<string:tag>", methods=["GET", "POST"])
def view_schedule(tag):
    schedule = db.session.query(ScheduleAttempt).filter_by(tag=tag).first()
    if schedule is None:
        abort(404)

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
            .filter(ScheduleSlot.owner_id == schedule.id, ScheduleSlot.session_id == selected_session.id)
            .join(Room, ScheduleSlot.room_id == Room.id)
            .join(Building, Room.building_id == Building.id)
            .order_by(Building.name.asc(), Room.name.asc())
            .all()
        )

    else:
        slots = []

    return render_template_context("admin/presentations/public/schedule.html", form=form, event=event, schedule=schedule, slots=slots)


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

    pclasses: List[ProjectClass] = db.session.query(ProjectClass).filter(ProjectClass.active, ProjectClass.id != sel.config.pclass_id).all()

    for pcl in pclasses:
        config: ProjectClassConfig = pcl.most_recent_config

        # reject if not gone live, since then we cannot match up project choices
        if not config.live:
            continue

        # reject if this student is already a selector for this project class
        if get_count(config.selecting_students.filter(SelectingStudent.student_id == sel.student_id)) > 0:
            continue

        available.add(config)

    if len(available) == 0:
        flash(
            'Selector <i class="fas fa-user-circle"></i> {name} cannot be moved at this time because there are no '
            "live project classes available as destinations.".format(name=sel.student.user.name),
            "info",
        )
        return redirect(url)

    return render_template_context("admin/move_selector.html", sel=sel, student=sel.student, available=available, url=url, text=text)


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
            "is already attached.".format(name=sel.student.user.name, pcl=dest_config.name),
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
    if get_count(dest_config.selecting_students.filter(SelectingStudent.student_id == sel.student_id)) > 0:
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
    tk_description = 'Move selector {name} to project class "{pcl}"'.format(name=sel.student.user.name, pcl=dest_config.name)
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    seq = chain(init.si(task_id, tk_name), move_selector.si(sid, dest_id, current_user.id), final.si(task_id, tk_name, current_user.id)).on_error(
        error.si(task_id, tk_name, current_user.id)
    )
    seq.apply_async(task_id=task_id)

    return redirect(url)


def create_new_template_tags(form):
    matched, unmatched = form.tags.data

    if len(unmatched) > 0:
        now = datetime.now()
        for tag in unmatched:
            new_tag = TemplateTag(name=tag, colour=None, creator_id=current_user.id, creation_timestamp=now)
            try:
                db.session.add(new_tag)
                matched.append(new_tag)
            except SQLAlchemyError as e:
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                flash(f'Could not add newly defined tag "{tag}" due to a database error. Please contact a system administrator.', "error")

    return matched


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
            with db.session.no_autoflush:
                asset = SubmittedAsset(
                    timestamp=datetime.now(), uploaded_id=current_user.id, expiry=None, target_name=form.label.data, license=form.license.data
                )

                object_store = current_app.config.get("OBJECT_STORAGE_PROJECT")
                with AssetUploadManager(
                    asset,
                    data=asset_file.stream.read(),
                    storage=object_store,
                    audit_data=f"upload_feedback_asset",
                    length=asset_file.content_length,
                    mimetype=asset_file.content_type,
                    validate_nonce=validate_nonce,
                ) as upload_mgr:
                    pass

            try:
                db.session.add(asset)
                db.session.flush()
            except SQLAlchemyError as e:
                db.session.rollback()
                flash("Could not upload feedback asset due to a database issue. Please contact an administrator.", "error")
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return redirect(url)

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
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                flash("Feedback asset was uploaded, but there was a database issue. Please contact an administrator.", "error")
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

            return redirect(url)

        else:
            flash("No upload was supplied", "error")

    return render_template_context("admin/feedback/upload_feedback_asset.html", form=form, url=url)


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
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("Could not save changes to this asset due to a database error. Please contact a system administrator.", "error")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)
    elif request.method == "GET":
        form.license.data = asset_record.license

    return render_template_context("admin/feedback/edit_feedback_asset.html", form=form, url=url, asset=asset)


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
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("Could not add feedback recipe due to a database issue. Please contact an administrator.", "error")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)

    return render_template_context("admin/feedback/add_feedback_recipe.html", form=form, url=url)


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
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("Could not save changes to this recipe due to a database issue. Please contact an administrator.", "error")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)

    return render_template_context("admin/feedback/edit_feedback_recipe.html", form=form, url=url, recipe=recipe)
