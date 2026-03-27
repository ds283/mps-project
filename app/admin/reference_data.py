#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import re
from datetime import datetime
from typing import List
from urllib.parse import urlsplit

from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    request,
    url_for,
)
from flask_security import (
    current_user,
    roles_accepted,
    roles_required,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import cast
from sqlalchemy.types import String

import app.ajax as ajax

from ..database import db
from ..models import (
    AssetLicense,
    DegreeProgramme,
    DegreeType,
    FacultyData,
    FHEQ_Level,
    MainConfig,
    Module,
    ProjectClass,
    ProjectClassConfig,
    ProjectTag,
    ProjectTagGroup,
    ResearchGroup,
    SkillGroup,
    SubmissionPeriodDefinition,
    SubmissionPeriodRecord,
    SubmissionRecord,
    Supervisor,
    Tenant,
    TransferableSkill,
)
from ..shared.context.global_context import render_template_context
from ..shared.utils import (
    get_current_year,
    get_main_config,
    home_dashboard,
    redirect_url,
)
from ..shared.validators import (
    validate_is_admin_or_convenor,
)
from ..shared.workflow_logging import log_db_commit
from ..tools import ServerSideSQLHandler
from . import admin
from .forms import (
    AddAssetLicenseForm,
    AddDegreeProgrammeForm,
    AddDegreeTypeForm,
    AddFHEQLevelForm,
    AddModuleForm,
    AddPeriodDefinitionFormFactory,
    AddProjectClassFormFactory,
    AddProjectTagForm,
    AddProjectTagGroupForm,
    AddResearchGroupForm,
    AddSkillGroupForm,
    AddSupervisorForm,
    AddTransferableSkillForm,
    EditAssetLicenseForm,
    EditDegreeProgrammeForm,
    EditDegreeTypeForm,
    EditFHEQLevelForm,
    EditModuleForm,
    EditPeriodDefinitionFormFactory,
    EditProjectClassFormFactory,
    EditProjectTagForm,
    EditProjectTagGroupForm,
    EditProjectTextForm,
    EditResearchGroupForm,
    EditSkillGroupForm,
    EditSupervisorForm,
    EditTransferableSkillForm,
    GlobalConfigForm,
    LevelSelectorForm,
)


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

        config.enable_2026_ATAS_campaign = form.enable_2026_ATAS_campaign.data

        try:
            log_db_commit("Updated global configuration settings", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes because of a database error. Please contact a system administrator",
                "error",
            )

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

    abbrv = {
        "search": ResearchGroup.abbreviation,
        "order": ResearchGroup.abbreviation,
        "search_collation": "utf8_general_ci",
    }
    active = {"order": ResearchGroup.active}
    name = {
        "search": ResearchGroup.name,
        "order": ResearchGroup.name,
        "search_collation": "utf8_general_ci",
    }
    colour = {
        "search": ResearchGroup.colour,
        "order": ResearchGroup.colour,
        "search_collation": "utf8_general_ci",
    }
    website = {
        "search": ResearchGroup.website,
        "order": ResearchGroup.website,
        "search_collation": "utf8_general_ci",
    }

    columns = {
        "abbrv": abbrv,
        "active": active,
        "name": name,
        "colour": colour,
        "website": website,
    }

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
            tenants=form.tenants.data,
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
            log_db_commit(f"Added new research group '{group.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add this affiliation group because of a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.edit_groups"))

    return render_template_context(
        "admin/edit_group.html", group_form=form, title="Add new affiliation"
    )


@admin.route("/edit_group/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_group(id):
    """
    View function to edit an existing research group
    :param id:
    :return:
    """
    group: ResearchGroup = ResearchGroup.query.get_or_404(id)
    form: EditResearchGroupForm = EditResearchGroupForm(obj=group)

    form.group = group

    if form.validate_on_submit():
        url = form.website.data
        if not re.match(r"http(s?):", url):
            url = "http://" + url
        r = urlsplit(url)  # canonicalize

        group.tenants = form.tenants.data
        group.abbreviation = form.abbreviation.data
        group.name = form.name.data
        group.colour = form.colour.data
        group.website = r.geturl()
        group.last_edit_id = current_user.id
        group.last_edit_timestamp = datetime.now()

        try:
            log_db_commit(f"Edited research group '{group.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes because of a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.edit_groups"))

    return render_template_context(
        "admin/edit_group.html", group_form=form, group=group, title="Edit affiliation"
    )


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
        log_db_commit(f"Activated research group '{group.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not save changes because of a database error. Please contact a system administrator",
            "error",
        )

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
        log_db_commit(f"Deactivated research group '{group.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not save changes because of a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@admin.route("/edit_degrees_types")
@roles_required("root")
def edit_degree_types():
    """
    View for editing degree types
    :return:
    """
    return render_template_context(
        "admin/degree_types/edit_degrees.html", subpane="degrees"
    )


@admin.route("/edit_degree_programmes")
@roles_required("root")
def edit_degree_programmes():
    """
    View for editing degree programmes
    :return:
    """
    return render_template_context(
        "admin/degree_types/edit_programmes.html", subpane="programmes"
    )


@admin.route("/edit_modules")
@roles_required("root")
def edit_modules():
    """
    View for editing modules
    :return:
    """
    return render_template_context(
        "admin/degree_types/edit_modules.html", subpane="modules"
    )


@admin.route("/edit_levels")
@roles_required("root")
def edit_levels():
    """
    View for editing FHEQ levels
    :return:
    """
    return render_template_context(
        "admin/degree_types/edit_levels.html", subpane="levels"
    )


@admin.route("/edit_levels_ajax", methods=["POST"])
@roles_required("root")
def edit_levels_ajax():
    """
    AJAX data point for FHEQ levels table
    :return:
    """
    base_query = db.session.query(FHEQ_Level)

    name = {
        "search": FHEQ_Level.name,
        "order": FHEQ_Level.name,
        "search_collation": "utf8_general_ci",
    }
    short_name = {
        "search": FHEQ_Level.short_name,
        "order": FHEQ_Level.short_name,
        "search_collation": "utf8_general_ci",
    }
    colour = {
        "search": FHEQ_Level.colour,
        "order": FHEQ_Level.colour,
        "search_collation": "utf8_general_ci",
    }
    numeric_level = {
        "order": FHEQ_Level.numeric_level,
        "search": cast(FHEQ_Level.numeric_level, String),
    }
    status = {"order": FHEQ_Level.active}

    columns = {
        "name": name,
        "short_name": short_name,
        "colour": colour,
        "numeric_level": numeric_level,
        "status": status,
    }

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

    name = {
        "search": DegreeType.name,
        "order": DegreeType.name,
        "search_collation": "utf8_general_ci",
    }
    level = {"order": DegreeType.level}
    duration = {
        "search": cast(DegreeType.duration, String),
        "order": DegreeType.duration,
    }
    colour = {
        "search": DegreeType.colour,
        "order": DegreeType.colour,
        "search_collation": "utf8_general_ci",
    }
    active = {"order": DegreeType.active}

    columns = {
        "name": name,
        "level": level,
        "duration": duration,
        "colour": colour,
        "active": active,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.admin.degree_types_data)


@admin.route("/degree_programmes_ajax", methods=["POST"])
@roles_required("root")
def degree_programmes_ajax():
    """
    Ajax data point for degree programmes tables
    :return:
    """
    base_query = db.session.query(DegreeProgramme).join(
        DegreeType, DegreeType.id == DegreeProgramme.type_id
    )

    name = {
        "search": DegreeProgramme.name,
        "order": DegreeProgramme.name,
        "search_collation": "utf8_general_ci",
    }
    type = {
        "search": DegreeType.name,
        "order": DegreeType.name,
        "search_collation": "utf8_general_ci",
    }
    show_type = {"order": DegreeProgramme.show_type}
    course_code = {
        "search": DegreeProgramme.course_code,
        "order": DegreeProgramme.course_code,
        "search_collation": "utf8_general_ci",
    }
    active = {"order": DegreeProgramme.active}

    columns = {
        "name": name,
        "type": type,
        "show_type": show_type,
        "course_code": course_code,
        "active": active,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.admin.degree_programmes_data)


@admin.route("/modules_ajax", methods=["POST"])
@roles_required("root")
def modules_ajax():
    """
    Ajax data point for module table
    :return:
    """
    base_query = db.session.query(Module).join(
        FHEQ_Level, FHEQ_Level.id == Module.level_id
    )

    code = {
        "search": Module.code,
        "order": Module.code,
        "search_collation": "utf8_general_ci",
    }
    name = {
        "search": Module.name,
        "order": Module.name,
        "search_collation": "utf8_general_ci",
    }
    level = {
        "search": FHEQ_Level.short_name,
        "order": FHEQ_Level.short_name,
        "search_collation": "utf8_general_ci",
    }
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
            log_db_commit(f"Added new degree type '{degree_type.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add a degree type because of a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.edit_degree_types"))

    return render_template_context(
        "admin/degree_types/edit_degree.html",
        type_form=form,
        title="Add new degree type",
    )


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
            log_db_commit(f"Edited degree type '{type.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes because of a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.edit_degree_types"))

    return render_template_context(
        "admin/degree_types/edit_degree.html",
        type_form=form,
        type=type,
        title="Edit degree type",
    )


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
        log_db_commit(f"Activated degree type '{degree_type.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not save changes because of a database error. Please contact a system administrator",
            "error",
        )

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
        log_db_commit(f"Deactivated degree type '{degree_type.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not save changes because of a database error. Please contact a system administrator",
            "error",
        )

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
        flash(
            "No degree types are available. Set up at least one active degree type before adding a degree programme.",
            "error",
        )
        return redirect(redirect_url())

    form = AddDegreeProgrammeForm(request.form)

    if form.validate_on_submit():
        degree_type = form.degree_type.data
        programme = DegreeProgramme(
            name=form.name.data,
            tenants=form.tenants.data,
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
            log_db_commit(f"Added new degree programme '{programme.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add a degree programme because of a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.edit_degree_programmes"))

    return render_template_context(
        "admin/degree_types/edit_programme.html",
        programme_form=form,
        title="Add new degree programme",
    )


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
        programme.tenants = form.tenants.data
        programme.abbreviation = form.abbreviation.data
        programme.show_type = form.show_type.data
        programme.course_code = form.course_code.data
        programme.foundation_year = form.foundation_year.data
        programme.year_out = form.year_out.data
        programme.year_out_value = (
            form.year_out_value.data if programme.year_out else None
        )
        programme.type_id = form.degree_type.data.id
        programme.last_edit_id = current_user.id
        programme.last_edit_timestamp = datetime.now()

        try:
            log_db_commit(f"Edited degree programme '{programme.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes because of a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.edit_degree_programmes"))

    return render_template_context(
        "admin/degree_types/edit_programme.html",
        programme_form=form,
        programme=programme,
        title="Edit degree programme",
    )


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
        log_db_commit(f"Activated degree programme '{programme.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not save changes because of a database error. Please contact a system administrator",
            "error",
        )

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
        log_db_commit(f"Deactivated degree programme '{programme.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not save changes because of a database error. Please contact a system administrator",
            "error",
        )

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
            form.selector.data = (
                FHEQ_Level.query.filter(FHEQ_Level.active.is_(True))
                .order_by(FHEQ_Level.numeric_level.asc())
                .first()
            )
        else:
            form.selector.data = FHEQ_Level.query.filter(
                FHEQ_Level.active.is_(True), FHEQ_Level.id == level_id
            ).first()

    # get list of modules for the current level_id
    if form.selector.data is not None:
        modules = Module.query.filter(
            Module.active.is_(True), Module.level_id == form.selector.data.id
        ).order_by(Module.semester.asc(), Module.name.asc())
    else:
        modules = []

    level_id = form.selector.data.id if form.selector.data is not None else None

    levels = (
        FHEQ_Level.query.filter_by(active=True)
        .order_by(FHEQ_Level.numeric_level.asc())
        .all()
    )

    return render_template_context(
        "admin/degree_types/attach_modules.html",
        prog=programme,
        modules=modules,
        form=form,
        level_id=level_id,
        levels=levels,
        title="Attach modules",
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
            log_db_commit(f"Attached module '{module.code} {module.name}' to degree programme '{programme.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes because of a database error. Please contact a system administrator",
                "error",
            )

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
            log_db_commit(f"Detached module '{module.code} {module.name}' from degree programme '{programme.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes because of a database error. Please contact a system administrator",
                "error",
            )

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
            log_db_commit(f"Added new FHEQ level '{level.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could add a FHEQ level because of a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.edit_levels"))

    return render_template_context(
        "admin/degree_types/edit_level.html", form=form, title="Add new FHEQ Level"
    )


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
            log_db_commit(f"Edited FHEQ level '{level.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes because of a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.edit_levels"))

    return render_template_context(
        "admin/degree_types/edit_level.html",
        form=form,
        level=level,
        title="Edit FHEQ Level",
    )


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
        log_db_commit(f"Activated FHEQ level '{level.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not save changes because of a database error. Please contact a system administrator",
            "error",
        )

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
        log_db_commit(f"Deactivated FHEQ level '{skill.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not save changes because of a database error. Please contact a system administrator",
            "error",
        )

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
        flash(
            "No FHEQ Levels are available. Set up at least one active FHEQ Level before adding a module.",
            "error",
        )
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
            log_db_commit(f"Added new module '{module.code} {module.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add a module because of a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.edit_modules"))

    return render_template_context(
        "admin/degree_types/edit_module.html", form=form, title="Add new module"
    )


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
        flash(
            'Module "{code} {name}" cannot be edited because it is retired.'.format(
                code=module.code, name=module.name
            ),
            "info",
        )
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
            log_db_commit(f"Edited module '{module.code} {module.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes because of a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.edit_modules"))

    return render_template_context(
        "admin/degree_types/edit_module.html",
        form=form,
        title="Edit module",
        module=module,
    )


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
        log_db_commit(f"Retired module '{module.code} {module.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not save changes because of a database error. Please contact a system administrator",
            "error",
        )

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
        log_db_commit(f"Un-retired module '{module.code} {module.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not save changes because of a database error. Please contact a system administrator",
            "error",
        )

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

    return render_template_context(
        "admin/transferable_skills/edit_skills.html", subpane="skills"
    )


@admin.route("/skills_ajax", methods=["POST"])
@roles_accepted("admin", "root", "faculty", "edit_tags")
def skills_ajax():
    """
    Ajax data point for transferable skills table
    :return:
    """
    if not validate_is_admin_or_convenor("edit_tags"):
        return jsonify({})

    base_query = db.session.query(TransferableSkill).join(
        SkillGroup, SkillGroup.id == TransferableSkill.group_id
    )

    name = {
        "search": TransferableSkill.name,
        "order": TransferableSkill.name,
        "search_collation": "utf8_general_ci",
    }
    group = {
        "search": SkillGroup.name,
        "order": SkillGroup.name,
        "search_collation": "utf8_general_ci",
    }
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
        flash(
            "No skill groups are available. Set up at least one active skill group before adding a transferable skill.",
            "error",
        )
        return redirect(redirect_url())

    form = AddTransferableSkillForm(request.form)

    if form.validate_on_submit():
        skill = TransferableSkill(
            name=form.name.data,
            group=form.group.data,
            active=True,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            db.session.add(skill)
            log_db_commit(f"Added new transferable skill '{skill.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add this skill group because of a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.edit_skills"))

    return render_template_context(
        "admin/transferable_skills/edit_skill.html",
        skill_form=form,
        title="Add new transferable skill",
    )


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
            log_db_commit(f"Edited transferable skill '{skill.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes because of a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.edit_skills"))

    return render_template_context(
        "admin/transferable_skills/edit_skill.html",
        skill_form=form,
        skill=skill,
        title="Edit transferable skill",
    )


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
        log_db_commit(f"Activated transferable skill '{skill.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not activate this transferable skill because of a database error. Please contact a system administrator",
            "error",
        )

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
        log_db_commit(f"Deactivated transferable skill '{skill.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not deactivate this transferable skill because of a database error. Please contact a system administrator",
            "error",
        )

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

    return render_template_context(
        "admin/transferable_skills/edit_skill_groups.html", subpane="groups"
    )


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

    name = {
        "search": SkillGroup.name,
        "order": SkillGroup.name,
        "search_collation": "utf8_general_ci",
    }
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
            log_db_commit(f"Added new transferable skill group '{group.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add new transferable skill group because of a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url_for("admin.edit_skill_groups"))

    return render_template_context(
        "admin/transferable_skills/edit_skill_group.html",
        group_form=form,
        title="Add new transferable skill group",
    )


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
            log_db_commit(f"Edited transferable skill group '{group.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes because of a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url_for("admin.edit_skill_groups"))

    return render_template_context(
        "admin/transferable_skills/edit_skill_group.html",
        group=group,
        group_form=form,
        title="Edit transferable skill group",
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
        log_db_commit(f"Activated transferable skill group '{group.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not activate this skill group because of a database error. Please contact a system administrator",
            "error",
        )

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
        log_db_commit(f"Deactivated transferable skill group '{group.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not deactivate this skill group because of a database error. Please contact a system administrator",
            "error",
        )

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

    return render_template_context(
        "admin/project_tags/edit_tag_groups.html", subpane="groups"
    )


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

    name = {
        "search": ProjectTagGroup.name,
        "order": ProjectTagGroup.name,
        "search_collation": "utf8_general_ci",
    }
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
            tenants=form.tenants.data,
            add_group=form.add_group.data,
            default=form.default.data,
            active=True,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            db.session.add(group)
            log_db_commit(f"Added new project tag group '{group.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add new project tag group because of a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url_for("admin.edit_project_tag_groups"))

    return render_template_context(
        "admin/project_tags/edit_tag_group.html",
        group_form=form,
        title="Add new project tag group",
    )


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
        group.tenants = form.tenants.data
        group.add_group = form.add_group.data
        group.default = form.default.data
        group.last_edit_id = current_user.id
        group.last_edit_timestamp = datetime.now()

        try:
            log_db_commit(f"Edited project tag group '{group.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes because of a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url_for("admin.edit_project_tag_groups"))

    return render_template_context(
        "admin/project_tags/edit_tag_group.html",
        group=group,
        group_form=form,
        title="Edit project tag group",
    )


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
        log_db_commit(f"Activated project tag group '{group.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not activate this project tag group because of a database error. Please contact a system administrator",
            "error",
        )

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
        flash(
            "Cannot disable this project tag group becuase it is currently the default group for new tags",
            "info",
        )
        return redirect(redirect_url())

    group.disable()

    try:
        log_db_commit(f"Deactivated project tag group '{group.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not disable this project tag group because of a database error. Please contact a system administrator",
            "error",
        )

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

    base_query = db.session.query(ProjectTag).join(
        ProjectTagGroup, ProjectTagGroup.id == ProjectTag.group_id
    )

    name = {
        "search": ProjectTag.name,
        "order": ProjectTag.name,
        "search_collation": "utf8_general_ci",
    }
    group = {
        "search": ProjectTagGroup.name,
        "order": ProjectTagGroup.name,
        "search_collation": "utf8_general_ci",
    }
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
        flash(
            "No project tag groups are available. Set up at least one active tag group before adding a tag.",
            "error",
        )
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
            log_db_commit(f"Added new project tag '{tag.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add this project tag because of a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.edit_project_tags"))

    return render_template_context(
        "admin/project_tags/edit_tag.html", tag_form=form, title="Add new project tag"
    )


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
            log_db_commit(f"Edited project tag '{tag.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes because of a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.edit_project_tags"))

    return render_template_context(
        "admin/project_tags/edit_tag.html",
        tag=tag,
        tag_form=form,
        title="Edit project tag",
    )


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
        log_db_commit(f"Activated project tag '{tag.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not activate this project tag because of a database error. Please contact a system administrator",
            "error",
        )

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
        log_db_commit(f"Deactivated project tag '{tag.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not disable this project tag because of a database error. Please contact a system administrator",
            "error",
        )

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
            log_db_commit(f"Added new content license '{data.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add new license because of a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("admin.edit_licenses"))

    return render_template_context(
        "admin/edit_license.html", form=form, title="Add new content license"
    )


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
            log_db_commit(f"Edited content license '{license.name}'", user=current_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                'Could not edit license "{name}" because of a database error. '
                "Please contact a system administrator".format(name=license.name),
                "error",
            )

        return redirect(url_for("admin.edit_licenses"))

    return render_template_context(
        "admin/edit_license.html",
        form=form,
        title="Edit content license",
        license=license,
    )


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
        log_db_commit(f"Activated content license '{license.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            'Could not activate license "{name}" due to a database error. '
            "Please contact a system administrator".format(name=license.name),
            "error",
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
        log_db_commit(f"Deactivated content license '{license.name}'", user=current_user)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            'Could not deactivate license "{name}" due to a database error. '
            "Please contact a system administrator".format(name=license.name),
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
        flash(
            "No degree types are available. Set up at least one active degree type before adding a project class."
        )
        return redirect(redirect_url())

    all_tenants: List[Tenant] = db.session.query(Tenant).all()
    AddProjectClassForm = AddProjectClassFormFactory(all_tenants)
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
                tenant=form.tenant.data,
                abbreviation=form.abbreviation.data,
                colour=form.colour.data,
                enforce_ATAS=form.enforce_ATAS.data,
                do_matching=form.do_matching.data,
                number_assessors=form.number_assessors.data,
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
            log_db_commit(f"Created new project class '{data.name}'", user=current_user, project_classes=data)

        except SQLAlchemyError as e:
            flash(
                "Could not create new project class because of a database error. Please contact a system administrator.",
                "error",
            )
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        flash(
            'Set convenor for "{title}" to {name}.'.format(
                name=data.convenor_name, title=data.name
            )
        )

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

    return render_template_context(
        "admin/edit_project_class.html", pclass_form=form, title="Add new project class"
    )


@admin.route("/edit_pclass/<int:id>", methods=["GET", "POST"])
@roles_required("root")
def edit_pclass(id):
    """
    Edit properties for an existing project class
    :param id:
    :return:
    """
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    allowed_tenants = [pclass.tenant]
    EditProjectClassForm = EditProjectClassFormFactory(allowed_tenants)
    form: EditProjectClassForm = EditProjectClassForm(obj=pclass)

    form.project_class = pclass

    # remember old convenor
    old_convenor: FacultyData = pclass.convenor

    if form.validate_on_submit():
        # make sure convenor and coconvenors don't have overlap
        coconvenors = form.coconvenors.data
        if form.convenor.data in coconvenors:
            coconvenors.remove(form.convenor.data)

        pclass.name = form.name.data
        pclass.abbreviation = form.abbreviation.data
        pclass.tenant = form.tenant.data
        pclass.enforce_ATAS = form.enforce_ATAS.data
        pclass.student_level = form.student_level.data
        pclass.start_year = form.start_year.data
        pclass.colour = form.colour.data
        pclass.is_optional = form.is_optional.data
        pclass.uses_selection = form.uses_selection.data
        pclass.uses_submission = form.uses_submission.data
        pclass.do_matching = form.do_matching.data
        pclass.number_assessors = form.number_assessors.data
        pclass.extent = form.extent.data
        pclass.require_confirm = form.require_confirm.data
        pclass.supervisor_carryover = form.supervisor_carryover.data
        pclass.include_available = form.include_available.data
        pclass.uses_supervisor = form.uses_supervisor.data
        pclass.uses_marker = form.uses_marker.data
        pclass.uses_moderator = form.uses_moderator.data
        pclass.uses_presentations = form.uses_presentations.data
        pclass.display_marker = form.display_marker.data
        pclass.display_presentations = form.display_presentations.data
        pclass.reenroll_supervisors_early = form.reenroll_supervisors_early.data
        pclass.convenor = form.convenor.data
        pclass.coconvenors = coconvenors
        pclass.office_contacts = form.office_contacts.data
        pclass.approvals_team = form.approvals_team.data
        pclass.select_in_previous_cycle = form.select_in_previous_cycle.data
        pclass.selection_open_to_all = form.selection_open_to_all.data
        pclass.auto_enrol_enable = form.auto_enrol_enable.data
        pclass.auto_enroll_years = form.auto_enroll_years.data
        pclass.advertise_research_group = form.advertise_research_group.data
        pclass.use_project_tags = form.use_project_tags.data
        pclass.force_tag_groups = form.force_tag_groups.data
        pclass.programmes = form.programmes.data
        pclass.initial_choices = form.initial_choices.data
        pclass.allow_switching = form.allow_switching.data
        pclass.switch_choices = form.switch_choices.data
        pclass.faculty_maximum = form.faculty_maximum.data
        pclass.CATS_supervision = form.CATS_supervision.data
        pclass.CATS_marking = form.CATS_marking.data
        pclass.CATS_moderation = form.CATS_moderation.data
        pclass.CATS_presentation = form.CATS_presentation.data
        pclass.keep_hourly_popularity = form.keep_hourly_popularity.data
        pclass.keep_daily_popularity = form.keep_daily_popularity.data
        pclass.last_edit_id = current_user.id
        pclass.last_edit_timestamp = datetime.now()

        if pclass.convenor.id != old_convenor.id:
            old_convenor.remove_convenorship(pclass)
            pclass.convenor.add_convenorship(pclass)

        try:
            db.session.flush()
            modified: bool = pclass.validate_presentations()
            log_db_commit(f"Edited project class '{pclass.name}'", user=current_user, project_classes=pclass)
        except SQLAlchemyError as e:
            db.session.rollback()
            flash(
                "Could not save project class configuration because of a database error. Please check the logs for further information.",
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        if pclass.convenor.id != old_convenor.id:
            flash(
                'Set convenor for "{title}" to {name}. The previous convenor was {oldname} and has been '
                "removed".format(
                    name=pclass.convenor_name,
                    oldname=old_convenor.user.name,
                    title=pclass.name,
                )
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

    return render_template_context(
        "admin/edit_project_class.html",
        pclass_form=form,
        pclass=pclass,
        title="Edit project class",
    )


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

        log_db_commit(f"Edited text content for project class '{data.name}'", user=current_user, project_classes=data)

        return redirect(url_for("admin.edit_project_classes"))

    return render_template_context(
        "admin/edit_pclass_text.html", form=form, pclass=data
    )


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
    log_db_commit(f"Activated project class '{data.name}'", user=current_user, project_classes=data)

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
    log_db_commit(f"Deactivated project class '{data.name}'", user=current_user, project_classes=data)

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
    log_db_commit(f"Published project class '{data.name}'", user=current_user, project_classes=data)

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
    log_db_commit(f"Unpublished project class '{data.name}'", user=current_user, project_classes=data)

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
    records = config.periods.order_by(
        SubmissionPeriodRecord.submission_period.asc()
    ).all()

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
                report_id=None,
                processed_report_id=None,
                celery_started=False,
                celery_finished=False,
                timestamp=False,
                report_exemplar=False,
                report_embargo=None,
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
        db.session.query(SubmissionRecord).filter_by(
            period_id=c.id, retired=False
        ).delete()
        db.session.delete(c)

    try:
        log_db_commit(f"Regenerated submission period records for project class '{data.name}'", user=current_user, project_classes=data)
    except SQLAlchemyError as e:
        flash(
            "Could not update submission period records for this project class due to a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
    else:
        flash(
            "Successfully updated submission period records for this project class",
            "info",
        )

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
            log_db_commit(f"Added new submission period definition '{pd.name}' to project class '{pclass.name}'", user=current_user,
                          project_classes=pclass)
        except SQLAlchemyError as e:
            flash(
                "Could not add new submission period definition because of a database error. Please contact a system administrator.",
                "error",
            )
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("admin.edit_period_definitions", id=pclass.id))

    return render_template_context(
        "admin/edit_period_definition.html",
        form=form,
        pclass_id=pclass.id,
        title="Add new submission period",
    )


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
            log_db_commit(f"Edited submission period definition '{pd.name}' for project class '{pd.owner.name}'", user=current_user,
                          project_classes=pd.owner)
        except SQLAlchemyError as e:
            flash(
                "Could not save changes because of a database error. Please contact a system administrator.",
                "error",
            )
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("admin.edit_period_definitions", id=pd.owner.id))

    return render_template_context(
        "admin/edit_period_definition.html",
        form=form,
        period=pd,
        title="Edit submission period",
    )


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
        log_db_commit(f"Deleted submission period definition from project class '{pclass.name}'", user=current_user, project_classes=pclass)
    except SQLAlchemyError as e:
        flash(
            "Could not delete submission period definition because of a database error. Please contact a system administrator.",
            "error",
        )
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

    role = {
        "search": Supervisor.name,
        "order": Supervisor.name,
        "search_collation": "utf8_general_ci",
    }
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
            log_db_commit(f"Added new supervisory role '{data.name}'", user=current_user)
        except SQLAlchemyError as e:
            flash(
                "Could not add new supervisory team member definition because of a database error. Please contact a system administrator.",
                "error",
            )
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("admin.edit_supervisors"))

    return render_template_context(
        "admin/edit_supervisor.html",
        supervisor_form=form,
        title="Add new supervisory role",
    )


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
            log_db_commit(f"Edited supervisory role '{data.name}'", user=current_user)
        except SQLAlchemyError as e:
            flash(
                "Could not save changes because of a database error. Please contact a system administrator.",
                "error",
            )
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("admin.edit_supervisors"))

    return render_template_context(
        "admin/edit_supervisor.html",
        supervisor_form=form,
        role=data,
        title="Edit supervisory role",
    )


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
        log_db_commit(f"Activated supervisory role '{data.name}'", user=current_user)
    except SQLAlchemyError as e:
        flash(
            "Could not activate supervisory team member because of a database error. Please contact a system administrator.",
            "error",
        )
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
        log_db_commit(f"Deactivated supervisory role '{data.name}'", user=current_user)
    except SQLAlchemyError as e:
        flash(
            "Could not deactivate supervisory team member because of a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())
