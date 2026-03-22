#
# Created by David Seery on 24/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from datetime import datetime
from functools import partial
from typing import List, Optional
from uuid import uuid4

from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)
from flask_security import current_user, roles_accepted
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import class_mapper
from sqlalchemy.sql import func, literal_column

import app.ajax as ajax
from app.convenor import convenor

from ..admin.forms import LevelSelectorForm
from ..database import db
from ..faculty.forms import (
    AddDescriptionFormFactory,
    AddProjectFormFactory,
    EditDescriptionContentForm,
    EditDescriptionSettingsFormFactory,
    EditProjectFormFactory,
    MoveDescriptionFormFactory,
    SkillSelectorForm,
)
from ..models import (
    ConfirmRequest,
    ConvenorGenericTask,
    CustomOffer,
    DegreeProgramme,
    FacultyData,
    FHEQ_Level,
    LiveProject,
    LiveProjectAlternative,
    Module,
    PopularityRecord,
    Project,
    ProjectAlternative,
    ProjectClass,
    ProjectClassConfig,
    ProjectDescription,
    ResearchGroup,
    SelectingStudent,
    SkillGroup,
    SubmittingStudent,
    TransferableSkill,
    User,
    WorkflowMixin,
)
from ..shared.context.convenor_dashboard import (
    build_convenor_tasks_query,
    get_convenor_dashboard_data,
)
from ..shared.context.global_context import render_template_context
from ..shared.convenor import (
    add_liveproject,
)
from ..shared.projects import (
    create_new_tags,
    get_filter_list_for_groups_and_skills,
    project_list_SQL_handler,
)
from ..shared.sqlalchemy import get_count
from ..shared.utils import (
    filter_assessors,
    get_convenor_filter_record,
    get_current_year,
    redirect_url,
)
from ..shared.validators import (
    validate_edit_description,
    validate_edit_project,
    validate_is_admin_or_convenor,
    validate_is_administrator,
    validate_is_convenor,
    validate_project_class,
    validate_view_project,
)
from ..tools import ServerSideSQLHandler
from .forms import (
    AddConvenorGenericTask,
    DuplicateProjectFormFactory,
    EditConvenorGenericTask,
    EditLiveProjectAlternativeForm,
    EditLiveProjectSupervisorsFactory,
    EditProjectAlternativeForm,
    EditProjectSupervisorsFactory,
)

STUDENT_TASKS_SELECTOR = SelectingStudent.polymorphic_identity()
STUDENT_TASKS_SUBMITTER = SubmittingStudent.polymorphic_identity()

# language=jinja2
_marker_menu = """
{% if proj.is_assessor(f.id) %}
 <a href="{{ url_for('convenor.remove_assessor', proj_id=proj.id, pclass_id=pclass_id, mid=f.id) }}"
    class="btn btn-sm full-width-button btn-secondary">
     <i class="fas fa-trash"></i> Remove
 </a>
{% elif proj.can_enroll_assessor(f) %}
 <a href="{{ url_for('convenor.add_assessor', proj_id=proj.id, pclass_id=pclass_id, mid=f.id) }}"
    class="btn btn-sm full-width-button btn-secondary">
     <i class="fas fa-plus"></i> Attach
 </a>
{% else %}
 <a class="btn btn-secondary full-width-button btn-sm disabled">
     <i class="fas fa-ban"></i> Can't attach
 </a>
{% endif %}
"""

# language=jinja2
_desc_label = """
{% set valid = not d.has_issues %}
{% if not valid %}
    <i class="fas fa-exclamation-triangle text-danger"></i>
{% endif %}
<a class="text-decoration-none" href="{{ url_for('faculty.project_preview', id=d.parent.id, pclass=desc_pclass_id,
                    url=url_for('convenor.edit_descriptions', id=d.parent.id, pclass_id=pclass_id, create=create),
                    text='description list view') }}">
    {{ d.label }}
</a>
<div>
    {% if d.review_only %}
        <span class="badge bg-info">Review project</span>
    {% endif %}
    {% set state = d.workflow_state %}
    {% set not_confirmed = d.requires_confirmation and not d.confirmed %}
    {% if not_confirmed %}
        {% if config is not none and config.selector_lifecycle == config.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS and desc_validator is not none and desc_validator(d) %}
            <div class="dropdown" style="display: inline-block;">
                <a class="badge text-decoration-none text-nohover-light bg-secondary dropdown-toggle" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">Approval: Not confirmed</a>
                <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                    <a class="dropdown-item d-flex gap-2" class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.confirm_description', config_id=config.id, did=d.id) }}"><i class="fas fa-check"></i> Confirm</a>
                </div>
            </div>
        {% else %}
            <span class="badge bg-secondary">Approval: Not confirmed</span>
        {% endif %}
    {% else %}
        {% if state == d.WORKFLOW_APPROVAL_VALIDATED %}
            <span class="badge bg-success"><i class="fas fa-check"></i> Approved</span>
        {% elif state == d.WORKFLOW_APPROVAL_QUEUED %}
            <span class="badge bg-warning text-dark">Approval: Confirmed</span>
        {% elif state == d.WORKFLOW_APPROVAL_REJECTED %}
            <span class="badge bg-info">Approval: In progress</span>
        {% else %}
            <span class="badge bg-danger">Approval: unknown state</span>
        {% endif %}
        {% if current_user.has_role('project_approver') and d.validated_by %}
            <div>
                <span class="badge bg-info">Signed-off: {{ d.validated_by.name }}</span>
                {% if d.validated_timestamp %}
                    <span class="badge bg-info">{{ d.validated_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}</span>
                {% endif %}
            </div>
        {% endif %}
    {% endif %}
    {% if d.has_new_comments(current_user) %}
        <span class="badge bg-warning text-dark">New comments</span>
    {% endif %}
</div>
{% if not valid %}
    <div class="mt-2">
        {% set errors = d.errors %}
        {% set warnings = d.warnings %}
        {{ error_block_popover(errors, warnings) }}
    </div>
{% endif %}
"""

# language=jinja2
_desc_menu = """
    <div class="dropdown">
        <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
            Actions
        </button>
        <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.project_preview', id=d.parent.id, pclass=pclass_id,
                                url=url_for('convenor.edit_descriptions', id=d.parent.id, pclass_id=pclass_id, create=create),
                                text='description list view') }}">
                <i class="fas fa-search fa-fw"></i> Preview web page
            </a>

            {% if desc_validator and desc_validator(d) %}
                <div role="separator" class="dropdown-divider"></div>
                <div class="dropdown-header">Edit description</div>
    
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_description', did=d.id, pclass_id=pclass_id, create=create,
                                                          url=url_for('convenor.edit_descriptions', id=d.parent_id, pclass_id=pclass_id, create=create),
                                                          text='project variants list') }}">
                    <i class="fas fa-sliders-h fa-fw"></i> Settings...
                </a>
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_description_content', did=d.id, pclass_id=pclass_id, create=create,
                                                          url=url_for('convenor.edit_descriptions', id=d.parent_id, pclass_id=pclass_id, create=create),
                                                          text='project variants list') }}">
                    <i class="fas fa-pencil-alt fa-fw"></i> Edit content...
                </a>
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.description_modules', did=d.id, pclass_id=pclass_id, create=create) }}">
                    <i class="fas fa-cogs fa-fw"></i> Recommended modules...
                </a>
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.duplicate_description', did=d.id, pclass_id=pclass_id) }}">
                    <i class="fas fa-clone fa-fw"></i> Duplicate
                </a>
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.move_description', did=d.id, pclass_id=pclass_id, create=create) }}">
                    <i class="fas fa-folder-open fa-fw"></i> Move to project...
                </a>
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.delete_description', did=d.id, pclass_id=pclass_id) }}">
                    <i class="fas fa-trash fa-fw"></i> Delete
                </a>
            {% endif %}
    
            <div role="separator" class="dropdown-divider"></div>

            {% if d.default is none %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.make_default_description', pid=d.parent_id, pclass_id=pclass_id, did=d.id) }}">
                    <i class="fas fa-wrench fa-fw"></i> Make default
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.make_default_description', pid=d.parent_id, pclass_id=pclass_id) }}">
                    <i class="fas fa-wrench fa-fw"></i> Remove default
                </a>
            {% endif %}
        </div>
    </div>
 """


@convenor.route("/edit_project_alternatives/<int:proj_id>")
@roles_accepted("faculty", "admin", "root")
def edit_project_alternatives(proj_id):
    # proj_id is a Project instance
    proj: Project = Project.query.get_or_404(proj_id)

    # reject user if not a convenor (or other suitable administrator)
    if not validate_is_admin_or_convenor():
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    return render_template_context(
        "convenor/projects/edit_alternatives.html", proj=proj, url=url, text=text
    )


@convenor.route("/edit_project_alternatives_ajax/<int:proj_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def edit_project_alternatives_ajax(proj_id):
    # proj_id is a Project instance
    proj: Project = Project.query.get_or_404(proj_id)

    # reject user if not a convenor (or other suitable administrator)
    if not validate_is_admin_or_convenor():
        return jsonify({})

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    base_query = proj.alternatives.join(
        Project, Project.id == ProjectAlternative.alternative_id
    )

    project = {
        "search": Project.name,
        "order": Project.name,
        "search_collation": "utf8_general_ci",
    }
    priority = {"order": ProjectAlternative.priority}

    columns = {"project": project, "priority": priority}

    with ServerSideSQLHandler(request, base_query, columns) as handler:

        def row_formatter(alternatives):
            return ajax.convenor.project_alternatives(alternatives, url=url, text=text)

        return handler.build_payload(row_formatter)


@convenor.route("/delete_project_alternative/<int:alt_id>")
@roles_accepted("faculty", "admin", "root")
def delete_project_alternative(alt_id):
    # alt_id is a ProjectAlternative instance
    alt: ProjectAlternative = ProjectAlternative.query.get_or_404(alt_id)

    # reject user if not a convenor (or other suitable administrator)
    if not validate_is_admin_or_convenor():
        return redirect(redirect_url())

    try:
        db.session.delete(alt)
        db.session.commit()
    except SQLAlchemyError as e:
        flash(
            "Could not delete project alternative because of a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/edit_project_alternative/<int:alt_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_project_alternative(alt_id):
    # alt_id is a ProjectAlternative instance
    alt: ProjectAlternative = ProjectAlternative.query.get_or_404(alt_id)

    # reject user if not a convenor (or other suitable administrator)
    if not validate_is_admin_or_convenor():
        return redirect(redirect_url())

    url = request.args.get("url", None)

    if url is None:
        url = url_for("convenor.edit_project_alternatives", proj_id=alt.parent_id)

    form = EditProjectAlternativeForm(obj=alt)

    if form.validate_on_submit():
        alt.priority = form.priority.data

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not modify project alternative properties due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "convenor/projects/edit_alternative.html", form=form, alt=alt, url=url
    )


@convenor.route("/new_project_alternative/<int:proj_id>")
@roles_accepted("faculty", "admin", "root")
def new_project_alternative(proj_id):
    # proj_id is a Project instance
    proj: Project = Project.query.get_or_404(proj_id)

    # reject user if not a convenor (or other suitable administrator)
    if not validate_is_admin_or_convenor():
        return redirect(redirect_url())

    url = request.args.get("url", None)

    return render_template_context(
        "convenor/projects/new_alternative.html", proj=proj, url=url
    )


@convenor.route("/new_project_alternative_ajax/<int:proj_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def new_project_alternative_ajax(proj_id):
    # proj_id is a Project instance
    proj: Project = Project.query.get_or_404(proj_id)

    # reject user if not a convenor (or other suitable administrator)
    if not validate_is_admin_or_convenor():
        return jsonify({})

    url = request.args.get("url", None)

    # get list of available projects, excluding any projects that are already alternatives for this one
    base_query = (
        db.session.query(Project)
        .filter(
            Project.active,
            ~Project.alternative_for.any(parent_id=proj.id),
            Project.id != proj_id,
        )
        .join(FacultyData, FacultyData.id == Project.owner_id, isouter=True)
        .join(User, User.id == FacultyData.id, isouter=True)
    )

    project = {
        "search": Project.name,
        "order": Project.name,
        "search_collation": "utf8_general_ci",
    }
    owner = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "search_collation": "utf8_general_ci",
        "order": [User.last_name, User.first_name],
    }
    columns = {"project": project, "owner": owner}

    with ServerSideSQLHandler(request, base_query, columns) as handler:

        def row_formatter(projects):
            return ajax.convenor.new_project_alternative(projects, proj, url)

        return handler.build_payload(row_formatter)


@convenor.route("/create_project_alternative/<int:proj_id>/<int:alt_proj_id>")
@roles_accepted("faculty", "admin", "root")
def create_project_alternative(proj_id, alt_proj_id):
    # proj_id is a Project instance
    proj: Project = Project.query.get_or_404(proj_id)

    # alt_lp_id is a LiveProject instance
    alt_proj: Project = Project.query.get_or_404(alt_proj_id)

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    # reject user if not a convenor (or other suitable administrator)
    if not validate_is_admin_or_convenor():
        return redirect(url)

    # check whether an ProjectAlternative with this parent and alternative already exists
    q = (
        db.session.query(ProjectAlternative)
        .filter(
            ProjectAlternative.parent_id == proj_id,
            ProjectAlternative.alternative_id == alt_proj_id,
        )
        .first()
    )
    if q is not None:
        flash(
            f'A request to create a project alternative for parent "{proj.name}" and alternative '
            f'"{alt_proj.name}" was ignored, because this combination already exists in the database.'
        )
        return redirect(url)

    alt = ProjectAlternative(parent_id=proj_id, alternative_id=alt_proj_id, priority=1)

    try:
        db.session.add(alt)
        db.session.commit()
    except SQLAlchemyError as e:
        flash(
            "Could not create alternative due to a database error. Please contact a system administrator",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(url)


@convenor.route("/edit_liveproject_alternatives/<int:lp_id>")
@roles_accepted("faculty", "admin", "root")
def edit_liveproject_alternatives(lp_id):
    # lp_id is a LiveProject instance
    lp: LiveProject = LiveProject.query.get_or_404(lp_id)

    # reject user if not a convenor (or other suitable administrator) for this project class
    if not validate_is_convenor(lp.config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    return render_template_context(
        "convenor/liveprojects/edit_alternatives.html", lp=lp, url=url, text=text
    )


@convenor.route("/edit_liveproject_alternatives_ajax/<int:lp_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def edit_liveproject_alternatives_ajax(lp_id):
    # lp_id is a LiveProject instance
    lp: LiveProject = LiveProject.query.get_or_404(lp_id)

    # reject user if not a convenor (or other suitable administrator) for this project class
    if not validate_is_convenor(lp.config.project_class):
        return jsonify({})

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    base_query = lp.alternatives.join(
        LiveProject, LiveProject.id == LiveProjectAlternative.alternative_id
    )

    project = {
        "search": LiveProject.name,
        "order": LiveProject.name,
        "search_collation": "utf8_general_ci",
    }
    priority = {"order": LiveProjectAlternative.priority}

    columns = {"project": project, "priority": priority}

    with ServerSideSQLHandler(request, base_query, columns) as handler:

        def row_formatter(alternatives):
            return ajax.convenor.liveproject_alternatives(
                alternatives, url=url, text=text
            )

        return handler.build_payload(row_formatter)


@convenor.route("/delete_liveproject_alternative/<int:alt_id>")
@roles_accepted("faculty", "admin", "root")
def delete_liveproject_alternative(alt_id):
    # alt_id is a LiveProjectAlternative instance
    alt: LiveProjectAlternative = LiveProjectAlternative.query.get_or_404(alt_id)

    # reject user if not a convenor (or other suitable administrator) for this project class
    if not validate_is_convenor(alt.parent.config.project_class):
        return redirect(redirect_url())

    try:
        db.session.delete(alt)
        db.session.commit()
    except SQLAlchemyError as e:
        flash(
            "Could not delete LiveProject alternative because of a database error. Please contact a system administrator.",
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/edit_liveproject_alternative/<int:alt_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_liveproject_alternative(alt_id):
    # alt_id is a LiveProjectAlternative instance
    alt: LiveProjectAlternative = LiveProjectAlternative.query.get_or_404(alt_id)

    # reject user if not a convenor (or other suitable administrator) for this project class
    if not validate_is_convenor(alt.parent.config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)

    if url is None:
        url = url_for(
            "convenor.edit_liveproject_alternatives",
            lp_id=alt.parent.id,
            url=url_for("convenor.liveprojects", id=alt.parent.config.project_class),
            text="convenor LiveProjects view",
        )

    form = EditLiveProjectAlternativeForm(obj=alt)

    if form.validate_on_submit():
        alt.priority = form.priority.data

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not modify LiveProject alternative properties due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "convenor/liveprojects/edit_alternative.html", form=form, alt=alt, url=url
    )


@convenor.route("/new_liveproject_alternative/<int:lp_id>")
@roles_accepted("faculty", "admin", "root")
def new_liveproject_alternative(lp_id):
    # lp_id is a LiveProject instance
    lp: LiveProject = LiveProject.query.get_or_404(lp_id)

    # reject user if not a convenor (or other suitable administrator) for this project class
    if not validate_is_convenor(lp.config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)

    return render_template_context(
        "convenor/liveprojects/new_alternative.html", lp=lp, url=url
    )


@convenor.route("/new_liveproject_alternative_ajax/<int:lp_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def new_liveproject_alternative_ajax(lp_id):
    # lp_id is a LiveProject instance
    lp: LiveProject = LiveProject.query.get_or_404(lp_id)

    # reject user if not a convenor (or other suitable administrator) for this project class
    if not validate_is_convenor(lp.config.project_class):
        return jsonify({})

    url = request.args.get("url", None)

    # get list of available projects, excluding any projects that are already alternatives for this one
    config: ProjectClassConfig = lp.config
    base_query = (
        config.live_projects.filter(
            ~LiveProject.alternative_for.any(parent_id=lp.id), LiveProject.id != lp_id
        )
        .join(FacultyData, FacultyData.id == LiveProject.owner_id, isouter=True)
        .join(User, User.id == FacultyData.id, isouter=True)
    )

    project = {
        "search": LiveProject.name,
        "order": LiveProject.name,
        "search_collation": "utf8_general_ci",
    }
    owner = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "search_collation": "utf8_general_ci",
        "order": [User.last_name, User.first_name],
    }
    columns = {"project": project, "owner": owner}

    with ServerSideSQLHandler(request, base_query, columns) as handler:

        def row_formatter(projects):
            return ajax.convenor.new_liveproject_alternative(projects, lp, url)

        return handler.build_payload(row_formatter)


@convenor.route("/create_liveproject_alternative/<int:lp_id>/<int:alt_lp_id>")
@roles_accepted("faculty", "admin", "root")
def create_liveproject_alternative(lp_id, alt_lp_id):
    # lp_id is a LiveProject instance
    lp: LiveProject = LiveProject.query.get_or_404(lp_id)

    # alt_lp_id is a LiveProject instance
    alt_lp: LiveProject = LiveProject.query.get_or_404(alt_lp_id)

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    # reject if lp and alt_lp don't belong to the same ProjectClassConfig
    if lp.config_id != alt_lp.config_id:
        flash(
            f'Projects "{lp.name}" and "{alt_lp.name}" do not belong to the same project cycle, '
            f"so they cannot be alternatives",
            "error",
        )
        return redirect(url)

    # reject user if not a convenor (or other suitable administrator) for this project class
    if not validate_is_convenor(lp.config.project_class):
        return redirect(url)

    # check whether an LiveProjectAlternative with this parent and alternative already exists
    q = (
        db.session.query(LiveProjectAlternative)
        .filter(
            LiveProjectAlternative.parent_id == lp_id,
            LiveProjectAlternative.alternative_id == alt_lp_id,
        )
        .first()
    )
    if q is not None:
        flash(
            f'A request to create a LiveProject alternative for parent "{lp.name}" and alternative '
            f'"{alt_lp.name}" was ignored, because this combination already exists in the database.'
        )
        return redirect(url)

    alt = LiveProjectAlternative(parent_id=lp_id, alternative_id=alt_lp_id, priority=1)

    try:
        db.session.add(alt)
        db.session.commit()
    except SQLAlchemyError as e:
        flash(
            "Could not create alternative due to a database error. Please contact a system administrator",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(url)


@convenor.route("/copy_alternative_to_library/<int:alt_id>")
@roles_accepted("faculty", "admin", "root")
def copy_alternative_to_library(alt_id):
    # alt_id is a LiveProjectAlternative instance
    alt: LiveProjectAlternative = LiveProjectAlternative.query.get_or_404(alt_id)

    # reject user if not a convenor (or other suitable administrator)
    if not validate_is_admin_or_convenor():
        return redirect(redirect_url())

    lp: LiveProject = alt.parent
    library_project: Project = lp.parent

    if library_project is None:
        flash(
            "Cannot copy this alternative to the main library, because no library project is linked to the parent LiveProject",
            "error",
        )
        return redirect(redirect_url())

    alt_lp: LiveProject = alt.alternative
    library_alt_project: Project = alt_lp.parent

    if library_alt_project is None:
        flash(
            "Cannot copy this alternative to the main library, because no library project is linked to the alternative LiveProject",
            "error",
        )
        return redirect(redirect_url())

    try:
        library_alt = (
            db.session.query(ProjectAlternative)
            .filter_by(
                parent_id=library_project.id, alternative_id=library_alt_project.id
            )
            .first()
        )
        if library_alt is None:
            library_alt = ProjectAlternative(
                parent_id=library_project.id,
                alternative_id=library_alt_project.id,
                priority=alt.priority,
            )
            db.session.add(library_alt)
            db.session.flush()

        # update priority if it has changed
        if alt.priority != library_alt.priority:
            library_alt.priority = alt.priority

        db.session.commit()

    except SQLAlchemyError as e:
        flash(
            "Could not create alternative due to a database error. Please contact a system administrator",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/copy_project_alternative_reciprocal/<int:alt_id>")
@roles_accepted("faculty", "admin", "root")
def copy_project_alternative_reciprocal(alt_id):
    # alt_id is a ProjectAlternative instance
    alt: ProjectAlternative = ProjectAlternative.query.get_or_404(alt_id)

    # reject user if not a convenor (or other suitable administrator)
    if not validate_is_admin_or_convenor():
        return redirect(redirect_url())

    rcp: Optional[ProjectAlternative] = alt.get_reciprocal()
    if rcp is not None:
        flash(
            "A request to create a reciprocal alternative was ignored, because the reciprocal is already present",
            "error",
        )
        return redirect(redirect_url())

    rcp = ProjectAlternative(
        parent_id=alt.alternative_id,
        alternative_id=alt.parent_id,
        priority=alt.priority,
    )

    try:
        db.session.add(rcp)
        db.session.commit()
    except SQLAlchemyError as e:
        flash(
            "Could not create alternative due to a database error. Please contact a system administrator",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/copy_liveproject_alternative_reciprocal/<int:alt_id>")
@roles_accepted("faculty", "admin", "root")
def copy_liveproject_alternative_reciprocal(alt_id):
    # alt_id is a LiveProjectAlternative instance
    alt: LiveProjectAlternative = LiveProjectAlternative.query.get_or_404(alt_id)

    # reject user if not a convenor (or other suitable administrator) for this project class
    if not validate_is_convenor(alt.parent.config.project_class):
        return redirect(redirect_url())

    rcp: Optional[ProjectAlternative] = alt.get_reciprocal()
    if rcp is not None:
        flash(
            "A request to create a reciprocal alternative was ignored, because the reciprocal is already present",
            "error",
        )
        return redirect(redirect_url())

    rcp = LiveProjectAlternative(
        parent_id=alt.alternative_id,
        alternative_id=alt.parent_id,
        priority=alt.priority,
    )

    try:
        db.session.add(rcp)
        db.session.commit()
    except SQLAlchemyError as e:
        flash(
            "Could not create alternative due to a database error. Please contact a system administrator",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/edit_project_supervisors/<int:proj_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_project_supervisors(proj_id):
    # proj_id labels a Project instance
    proj: Project = Project.query.get_or_404(proj_id)

    # reject if user is not a suitable convenor or administrator
    if not validate_is_admin_or_convenor():
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.liveprojects", id=proj.config.pclass_id)

    EditProjectSupervisorsForm = EditProjectSupervisorsFactory(proj)
    form = EditProjectSupervisorsForm(obj=proj)

    if form.validate_on_submit():
        proj.supervisors = form.supervisors.data

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash(
                "Could not save changes to supervisor pool because of a database error. Please contact a system administrator",
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            db.session.rollback()

        return redirect(url)

    return render_template_context(
        "convenor/projects/edit_supervisors.html", form=form, proj=proj, url=url
    )


@convenor.route("/edit_liveproject_supervisors/<int:proj_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_liveproject_supervisors(proj_id):
    # proj_id labels a LiveProject instance
    proj: LiveProject = LiveProject.query.get_or_404(proj_id)

    # reject is user is not a suitable convenor or administrator
    if not validate_is_convenor(proj.config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.liveprojects", id=proj.config.pclass_id)

    EditLiveProjectSupervisorsForm = EditLiveProjectSupervisorsFactory(proj)
    form = EditLiveProjectSupervisorsForm(obj=proj)

    if form.validate_on_submit():
        proj.supervisors = form.supervisors.data

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash(
                "Could not save changed to supervisor pool because of a database error. Please contact a system administrator",
                "error",
            )
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            db.session.rollback()

        return redirect(url)

    return render_template_context(
        "convenor/liveprojects/edit_supervisors.html", form=form, proj=proj, url=url
    )


@convenor.route("/liveprojects/<int:id>")
@roles_accepted("faculty", "admin", "root")
def liveprojects(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    state_filter = request.args.get("state_filter")
    type_filter = request.args.get("type_filter")

    if state_filter is None and session.get("convenor_liveprojects_state_filter"):
        state_filter = session["convenor_liveprojects_state_filter"]

    if state_filter not in [
        "all",
        "submitted",
        "bookmarks",
        "none",
        "confirmations",
        "custom",
    ]:
        state_filter = "all"

    if state_filter is not None:
        session["convenor_liveprojects_state_filter"] = state_filter

    if type_filter is None and session.get("convenor_liveprojects_type_filter"):
        type_filter = session["convenor_liveprojects_type_filter"]

    if type_filter not in ["all", "generic", "hidden", "alternatives"]:
        type_filter = "all"

    if type_filter is not None:
        session["convenor_liveprojects_type_filter"] = type_filter

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    data = get_convenor_dashboard_data(pclass, config)

    # supply list of transferable skill groups and research groups that can be filtered against
    groups, skill_list = get_filter_list_for_groups_and_skills(pclass)

    # get filter record
    filter_record = get_convenor_filter_record(config)

    return render_template_context(
        "convenor/dashboard/liveprojects.html",
        pane="live",
        subpane="list",
        pclass=pclass,
        config=config,
        convenor_data=data,
        current_year=current_year,
        groups=groups,
        skill_groups=sorted(skill_list.keys()),
        skill_list=skill_list,
        filter_record=filter_record,
        state_filter=state_filter,
        type_filter=type_filter,
    )


@convenor.route("/liveprojects_ajax/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def liveprojects_ajax(id):
    """
    AJAX endpoint for liveprojects fiew
    :param id:
    :return:
    """
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    state_filter = request.args.get("state_filter")
    type_filter = request.args.get("type_filter")

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return jsonify({})

    popularity_subq = (
        db.session.query(
            PopularityRecord.liveproject_id.label("popq_liveproject_id"),
            func.max(PopularityRecord.datestamp).label("popq_datestamp"),
        )
        .filter(PopularityRecord.score_rank != None)
        .group_by(PopularityRecord.liveproject_id)
        .subquery()
    )

    base_query = (
        config.live_projects.join(
            FacultyData, FacultyData.id == LiveProject.owner_id, isouter=True
        )
        .join(User, User.id == FacultyData.id, isouter=True)
        .join(
            popularity_subq,
            popularity_subq.c.popq_liveproject_id == LiveProject.id,
            isouter=True,
        )
        .join(
            PopularityRecord,
            and_(
                PopularityRecord.liveproject_id
                == popularity_subq.c.popq_liveproject_id,
                PopularityRecord.datestamp == popularity_subq.c.popq_datestamp,
            ),
            isouter=True,
        )
    )

    # get FilterRecord for currently logged-in user
    filter_record = get_convenor_filter_record(config)

    valid_group_ids = [g.id for g in filter_record.group_filters]
    valid_skill_ids = [s.id for s in filter_record.skill_filters]

    if pclass.advertise_research_group and len(valid_group_ids) > 0:
        base_query = base_query.filter(LiveProject.group_id.in_(valid_group_ids))

    if len(valid_skill_ids) > 0:
        base_query = base_query.filter(
            LiveProject.skills.any(TransferableSkill.id.in_(valid_skill_ids))
        )

    return _liveprojects_ajax_handler(base_query, config, state_filter, type_filter)


def _liveprojects_ajax_handler(
    base_query, config: ProjectClassConfig, state_filter: str, type_filter: str
):
    if type_filter == "generic":
        base_query = base_query.filter(LiveProject.generic.is_(True))
    elif type_filter == "hidden":
        base_query = base_query.filter(LiveProject.hidden.is_(True))
    elif type_filter == "alternatives":
        base_query = base_query.join(
            LiveProjectAlternative, LiveProjectAlternative.parent_id == LiveProject.id
        ).distinct()

    if state_filter == "submitter":
        base_query = base_query.filter(func.count(LiveProject.submitted) > 0)
    elif state_filter == "bookmarks":
        base_query = base_query.filter(
            and_(
                func.count(LiveProject.selections) == 0,
                func.count(LiveProject.bookmarks) > 0,
            )
        )
    elif state_filter == "none":
        base_query = base_query.filter(
            and_(
                func.count(LiveProject.selections) == 0,
                func.count(LiveProject.bookmarks) == 0,
            )
        )
    elif state_filter == "confirmations":
        base_query = (
            base_query.join(
                ConfirmRequest,
                ConfirmRequest.project_id == LiveProject.id,
                isouter=True,
            )
            .filter(ConfirmRequest.state == ConfirmRequest.REQUESTED)
            .distinct()
        )
    elif state_filter == "custom":
        base_query = base_query.join(
            CustomOffer, CustomOffer.liveproject_id == LiveProject.id
        ).distinct()

    name = {
        "search": LiveProject.name,
        "order": LiveProject.name,
        "search_collation": "utf8_general_ci",
    }
    owner = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "order": [User.last_name, User.first_name],
        "search_collation": "utf8_general_ci",
    }
    bookmarks = {
        "order": [PopularityRecord.bookmarks, PopularityRecord.score, LiveProject.name]
    }
    selections = {
        "order": [PopularityRecord.selections, PopularityRecord.score, LiveProject.name]
    }
    popularity = {
        "order": [
            PopularityRecord.score_rank,
            PopularityRecord.selections_rank,
            PopularityRecord.bookmarks_rank,
            LiveProject.name,
        ]
    }

    columns = {
        "name": name,
        "owner": owner,
        "bookmarks": bookmarks,
        "selections": selections,
        "popularity": popularity,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:

        def row_formatter(liveprojects):
            return ajax.convenor.liveprojects_data(
                liveprojects,
                config,
                url=url_for("convenor.liveprojects", id=config.pclass_id),
                text="convenor LiveProjects view",
            )

        return handler.build_payload(row_formatter)


@convenor.route("/delete_live_project/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def delete_live_project(pid):
    """
    User front-end to delete a live project that is still in the selection phase
    :param pid:
    :return:
    """
    project: LiveProject = LiveProject.query.get_or_404(pid)

    # get ProjectClassConfig that this LiveProject belongs to
    config: ProjectClassConfig = project.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    # reject if project is not deletable
    if not project.is_deletable:
        flash(
            'Cannot delete live project "{name}" because it is marked as not removable.'.format(
                name=project.name
            ),
            "error",
        )
        return redirect(redirect_url())

    # if this config has closed selections, we cannot delete any live projects
    if config.selection_closed:
        flash(
            'Cannot delete LiveProjects belonging to class "{cls}" in the {yra}-{yrb} cycle, '
            "because selections have already closed".format(
                cls=config.name, yra=config.submit_year_a, yrb=config.submit_year_b
            ),
            "info",
        )
        return redirect(redirect_url())

    title = (
        'Delete LiveProject "{name}" for project class "{cls}" in '
        "{yra}&ndash;{yrb}".format(
            name=project.name,
            cls=config.name,
            yra=config.submit_year_a,
            yrb=config.submit_year_b,
        )
    )
    action_url = url_for("convenor.perform_delete_live_project", pid=pid)
    message = (
        '<p>Please confirm that you wish to delete the live project "{name}" belonging to '
        'project class "{cls}" {yra}&ndash;{yrb}.</p>'
        "<p>This action cannot be undone.</p>".format(
            name=project.name,
            cls=config.name,
            yra=config.submit_year_a,
            yrb=config.submit_year_b,
        )
    )
    submit_label = "Delete live project"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@convenor.route("/perform_delete_live_project/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def perform_delete_live_project(pid):
    """
    Delete a live project that is still in the selection phase
    :param pid:
    :return:
    """
    project: LiveProject = LiveProject.query.get_or_404(pid)

    # get ProjectClassConfig that this LiveProject belongs to
    config: ProjectClassConfig = project.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    # reject if project is not deletable
    if not project.is_deletable:
        flash(
            'Cannot delete live project "{name}" because it is marked as undeletable.'.format(
                name=project.name
            ),
            "error",
        )
        return redirect(redirect_url())

    # if this config has closed selections, we cannot delete any live projects
    if config.selection_closed:
        flash(
            'Cannot delete LiveProjects belonging to class "{cls}" in the {yra}-{yrb} cycle, '
            "because selections have already closed".format(
                cls=config.name, yra=config.submit_year_a, yrb=config.submit_year_b
            ),
            "info",
        )
        return redirect(redirect_url())

    try:
        # remove all collections associated with the liveproject
        project.skills = []
        project.programmes = []
        project.team = []
        project.assessors = []
        project.modules = []
        db.session.flush()

        # remove all confirmation requests
        for req in project.confirmation_requests:
            db.session.delete(req)

        # remove all bookmarks
        for bkm in project.bookmarks:
            db.session.delete(bkm)

        # remove all selections
        for sel in project.selections:
            db.session.delete(sel)

        # remove all custom offers
        for cof in project.custom_offers:
            db.session.delete(cof)

        # remove all popularity data
        for pdt in project.popularity_data:
            db.session.delete(pdt)

        db.session.flush()

        db.session.delete(project)
        db.session.commit()

    except SQLAlchemyError as e:
        flash(
            'Could not delete live project "{name}" because of a database error. '
            "Please contact a system administrator.".format(name=project.name),
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url_for("convenor.liveprojects", id=config.pclass_id))


@convenor.route("/hide_liveproject/<int:id>")
@roles_accepted("faculty", "admin", "root")
def hide_liveproject(id):
    """
    Mark a LiveProject as hidden, ie. not published in the global list
    :param id:
    :return:
    """
    # get LiveProject
    project: LiveProject = LiveProject.query.get_or_404(id)

    # get ProjectClassConfig that this LiveProject belongs to
    config: ProjectClassConfig = project.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    # not entirely clear that hiding/unhiding should be forbidden after selections close, but it has no
    # meaning, so nothing seems lost by disallowing it.
    # This also preserves the database record.
    if config.selection_closed:
        flash(
            'Cannot hide LiveProjects belonging to class "{cls}" in the {yra}-{yrb} cycle, '
            "because selections have already closed".format(
                cls=config.name, yra=config.submit_year_a, yrb=config.submit_year_b
            ),
            "info",
        )
        return redirect(redirect_url())

    try:
        project.hidden = True
        db.session.commit()

    except SQLAlchemyError as e:
        flash(
            'Could not hide live project "{name}" because of a database error. '
            "Please contact a system administrator.".format(name=project.name),
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/unhide_liveproject/<int:id>")
@roles_accepted("faculty", "admin", "root")
def unhide_liveproject(id):
    """
    Mark a LiveProject as hidden, ie. not published in the global list
    :param id:
    :return:
    """
    # get LiveProject
    project: LiveProject = LiveProject.query.get_or_404(id)

    # get ProjectClassConfig that this LiveProject belongs to
    config: ProjectClassConfig = project.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    # not entirely clear that hiding/unhiding should be forbidden after selections close, but it has no
    # meaning, so nothing seems lost by disallowing it.
    # This also preserves the database record.
    if config.selection_closed:
        flash(
            'Cannot unhide LiveProjects belonging to class "{cls}" in the {yra}-{yrb} cycle, '
            "because selections have already closed".format(
                cls=config.name, yra=config.submit_year_a, yrb=config.submit_year_b
            ),
            "info",
        )
        return redirect(redirect_url())

    try:
        project.hidden = False
        db.session.commit()

    except SQLAlchemyError as e:
        flash(
            'Could not unhide live project "{name}" because of a database error. '
            "Please contact a system administrator.".format(name=project.name),
            "error",
        )
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/attach_liveproject/<int:id>")
@roles_accepted("faculty", "admin", "root")
def attach_liveproject(id):
    """
    Allow manual attachment of projects
    :param id:
    :return:
    """
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    # reject if project class is not live
    if not config.live:
        flash(
            "Manual attachment of projects is only possible after Go Live for this academic year",
            "error",
        )
        return redirect(redirect_url())

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/attach_liveproject.html",
        pane="live",
        subpane="attach",
        pclass=pclass,
        config=config,
        convenor_data=data,
    )


@convenor.route("/attach_liveproject_ajax/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def attach_liveproject_ajax(id):
    """
    AJAX endpoint for attach_liveproject view - projects available to be attached
    :param id:
    :return:
    """
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        return jsonify({})

    if not config.live:
        return jsonify({})

    # compute all active projects registered for this project class, that do not have a LiveProject equivalent
    base_query = pclass.projects.filter(Project.active.is_(True))

    # get existing liveprojects, and remove any counterparts
    current_projects = [p.parent_id for p in config.live_projects]
    base_query = base_query.filter(Project.id.not_in(current_projects))

    # restrict query to projects owned by active users, or generic projects
    base_query = base_query.join(
        User, User.id == Project.owner_id, isouter=True
    ).filter(or_(Project.generic.is_(True), User.active.is_(True)))

    # remove projects that don't have a description
    base_query = base_query.join(
        ProjectDescription, ProjectDescription.parent_id == Project.id
    ).filter(ProjectDescription.project_classes.any(id=pclass.id))

    return project_list_SQL_handler(
        request,
        base_query,
        current_user=current_user,
        config=config,
        menu_template="attach",
        name_labels=True,
        text="attach projects view",
        url=url_for("convenor.attach_liveproject", id=id),
        show_approvals=True,
        show_errors=True,
    )


@convenor.route("/manual_attach_project/<int:id>/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def manual_attach_project(id, configid):
    """
    Manually attach a project
    :param id:
    :param configid:
    :return:
    """
    # TODO - work out what logic can be consolidated between manual_attach_project() and inject_liveproject()

    # reject if desired project is not attachable
    project: Project = Project.query.get_or_404(id)
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(configid)

    # reject user if not entitled to act as convenor
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class is not live
    if not config.live:
        flash(
            "Manual attachment of projects is only possible after Go Live for this academic year",
            "error",
        )
        return redirect(redirect_url())

    if config.project_class not in project.project_classes:
        flash(
            'Could not attach LiveProject "{proj}" to project class "{pcl}" because this project '
            "is not attached to that class.".format(proj=project.name, pcl=config.name),
            "info",
        )
        return redirect(redirect_url())

    desc: ProjectDescription = project.get_description(config.project_class)
    if desc is None:
        flash(
            'Project "{p}" does not have a description for "{c}" and cannot be '
            "attached.".format(p=project.name, c=config.name)
        )
        return redirect(redirect_url())

    try:
        # passing number=None to add_liveproject() causes it to assign its own number
        add_liveproject(None, project, configid, autocommit=True)
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            f'Could not attach LiveProject "{project.name}" due to a database error. Please contact a system administrator',
            "error",
        )
    else:
        flash(
            f'LiveProject "{project.name}" has been published to students.', "success"
        )

    return redirect(redirect_url())


@convenor.route("/attach_liveproject_other_ajax/<int:id>", methods=["POST"])
@roles_accepted("admin", "root")
def attach_liveproject_other_ajax(id):
    """
    AJAX endpoint for attach_liveproject view - projects attached to *other* project classes that we might wish to attach
    :param id:
    :return:
    """

    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        return jsonify({})

    if not config.live:
        return jsonify({})

    # find all projects, not already attached as LiveProjects, that are not attached to
    # this project class
    base_query = db.session.query(Project, ProjectDescription).filter(
        Project.active.is_(True),
        ~Project.project_classes.any(ProjectClass.id == pclass.id),
        ProjectDescription.parent_id == Project.id,
    )

    # get existing liveprojects attached to this config instance
    current_projects = [p.parent_id for p in config.live_projects]

    # don't show these existing attached liveprojects
    base_query = base_query.filter(Project.id.not_in(current_projects))

    # don't offer to attach projects attached to this project class
    base_query = base_query

    # restrict query to projects owned by active users, or generic projects
    base_query = base_query.join(
        User, User.id == Project.owner_id, isouter=True
    ).filter(or_(Project.generic.is_(True), User.active.is_(True)))

    return project_list_SQL_handler(
        request,
        base_query,
        current_user=current_user,
        config=config,
        menu_template="attach_other",
        name_labels=True,
        text="attach projects view",
        url=url_for("convenor.attach_liveproject", id=id),
        show_approvals=True,
        show_errors=True,
    )


@convenor.route("/manual_attach_other_project/<int:id>/<int:configid>")
@roles_accepted("admin", "root")
def manual_attach_other_project(id, configid):
    """
    Manually attach a project
    :param id:
    :param configid:
    :return:
    """
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(configid)

    # reject if project class is not live
    if not config.live:
        flash(
            "Manual attachment of projects is only possible after Go Live for this academic year",
            "error",
        )
        return redirect(redirect_url())

    # get number for this project
    desc: ProjectDescription = ProjectDescription.query.get_or_404(id)

    # passing number=None to add_liveproject() causes it to assign its own number
    add_liveproject(None, desc.parent, configid, desc=desc, autocommit=True)

    return redirect(redirect_url())


@convenor.route("/todo_list/<int:id>")
@roles_accepted("faculty", "admin", "root")
def todo_list(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    status_filter = request.args.get("status_filter")

    if status_filter is None and session.get("convenor_todo_list_status_filter"):
        status_filter = session["convenor_todo_list_status_filter"]

    if status_filter is not None and status_filter not in [
        "default",
        "overdue",
        "available",
        "dropped",
        "completed",
    ]:
        status_filter = "default"

    if status_filter is not None:
        session["convenor_todo_list_status_filter"] = status_filter

    blocking_filter = request.args.get("blocking_filter")

    if blocking_filter is None and session.get("convenor_todo_list_blocking_filter"):
        blocking_filter = session["convenor_todo_list_blocking_filter"]

    if blocking_filter is not None and blocking_filter not in [
        "all",
        "blocking",
        "not-blocking",
    ]:
        blocking_filter = "all"

    if blocking_filter is not None:
        session["convenor_todo_list_blocking_filter"] = blocking_filter

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/todo_list.html",
        pane="todo",
        pclass=pclass,
        config=config,
        convenor_date=data,
        current_year=current_year,
        status_filter=status_filter,
        blocking_filter=blocking_filter,
        convenor_data=data,
    )


@convenor.route("/todo_list_ajax/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def todo_list_ajax(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        return jsonify({})

    status_filter = request.args.get("status_filter", "all")
    blocking_filter = request.args.get("blocking_filter", "all")

    base_query = build_convenor_tasks_query(
        config,
        status_filter=status_filter,
        blocking_filter=blocking_filter,
        due_date_order=False,
    )

    # set up columns for server-side processing;
    # use column literals because the query returned from base_query is likely to be built using
    # polymorphic objects
    task = {
        "search": literal_column("description"),
        "order": literal_column("description"),
        "search_collation": "utf8_general_ci",
    }
    defer_date = {
        "search": literal_column('DATE_FORMAT(defer_date, "%a %d %b %Y %H:%M:%S")'),
        "order": literal_column("defer_date"),
        "search_collation": "utf8_general_ci",
    }
    due_date = {
        "search": literal_column('DATE_FORMAT(due_date, "%a %d %b %Y %H:%M:%S")'),
        "order": literal_column("due_date"),
        "search_collation": "utf8_general_ci",
    }
    status = {
        "order": literal_column(
            "(NOT(complete OR dropped) * (100*(due_date > CURDATE()) + 50*(defer_date > CURDATE())) + 10*complete + 1*dropped)"
        )
    }

    columns = {
        "task": task,
        "defer_date": defer_date,
        "due_date": due_date,
        "status": status,
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(partial(ajax.convenor.todo_list_data, pclass.id))


@convenor.route("/add_generic_task/<int:config_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def add_generic_task(config_id):
    # get details for project class config record
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(config_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    form = AddConvenorGenericTask(request.form)
    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.todo_list", id=config.pclass_id)

    if form.validate_on_submit():
        task = ConvenorGenericTask(
            description=form.description.data,
            notes=form.notes.data,
            blocking=form.blocking.data,
            complete=form.complete.data,
            dropped=form.dropped.data,
            defer_date=form.defer_date.data,
            due_date=form.due_date.data,
            repeat=form.repeat.data,
            repeat_interval=form.repeat_interval.data,
            repeat_frequency=form.repeat_frequency.data,
            repeat_from_due_date=form.repeat_from_due_date.data,
            rollover=form.rollover.data,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            config.tasks.append(task)
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not create new task due to a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "convenor/tasks/edit_generic_task.html", form=form, url=url, config=config
    )


@convenor.route("/edit_generic_task/<int:tid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_generic_task(tid):
    # get details for task
    task: AddConvenorGenericTask = ConvenorGenericTask.query.get_or_404(tid)
    config: ProjectClassConfig = task.parent

    if config is None:
        flash(
            "Cannot edit this task because it is orphaned, or because a polymorphism loading "
            "error has occurred. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    form = EditConvenorGenericTask(obj=task)
    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.todo_list", id=config.pclass_id)

    if form.validate_on_submit():
        task.description = form.description.data
        task.notes = form.notes.data
        task.blocking = form.blocking.data
        task.complete = form.complete.data
        task.dropped = form.dropped.data
        task.defer_date = form.defer_date.data
        task.due_date = form.due_date.data
        task.repeat = form.repeat.data
        task.repeat_interval = form.repeat_interval.data
        task.repeat_frequency = form.repeat_frequency.data
        task.repeat_from_due_date = form.repeat_from_due_date.data
        task.rollover = form.rollover.data
        task.last_edit_id = current_user.id
        task.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes to task due to a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "convenor/tasks/edit_generic_task.html",
        form=form,
        url=url,
        task=task,
        config=config,
    )


@convenor.route("/edit_descriptions/<int:id>/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def edit_descriptions(id, pclass_id):
    # get project details
    project = Project.query.get_or_404(id)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

        if not validate_view_project(project):
            return redirect(redirect_url())

    create = request.args.get("create", default=None)

    return render_template_context(
        "convenor/projects/edit_descriptions.html",
        project=project,
        pclass_id=pclass_id,
        create=create,
    )


@convenor.route("/descriptions_ajax/<int:id>/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def descriptions_ajax(id, pclass_id):
    # get project details
    project = Project.query.get_or_404(id)

    if not validate_view_project(project):
        return jsonify({})

    pclass = None
    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return jsonify({})

    else:
        # get project class details
        pclass: ProjectClass = (
            db.session.query(ProjectClass).filter_by(id=pclass_id).first()
        )

        # if logged-in user is not a suitable convenor, or an administrator, object
        if pclass is not None and not validate_is_convenor(pclass):
            return jsonify({})

    # get current configuration record for this project class
    config = None
    if pclass is not None:
        config: ProjectClassConfig = pclass.most_recent_config

    descs = project.descriptions.all()

    create = request.args.get("create", default=None)

    return ajax.faculty.descriptions_data(
        descs,
        _desc_label,
        _desc_menu,
        pclass_id=pclass_id,
        create=create,
        config=config,
        desc_validator=validate_edit_description,
    )


@convenor.route("/add_project/<int:pclass_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def add_project(pclass_id):
    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

        # if the logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

    # set up form
    AddProjectForm = AddProjectFormFactory(
        current_user.tenants.all(),
        convenor_editing=True,
        uses_tags=True,
        uses_research_groups=True,
    )
    form = AddProjectForm(request.form)

    if form.validate_on_submit():
        allowed_tenants = [pclass.tenant]
        tag_list = create_new_tags(form, allowed_tenants)
        project = Project(
            name=form.name.data,
            tags=tag_list,
            active=True,
            owner=form.owner.data if not form.generic.data else None,
            generic=form.generic.data,
            ATAS_restricted=form.ATAS_restricted.data,
            group=form.group.data,
            project_classes=form.project_classes.data,
            skills=[],
            programmes=[],
            meeting_reqd=form.meeting_reqd.data,
            enforce_capacity=form.enforce_capacity.data,
            show_popularity=form.show_popularity.data,
            show_bookmarks=form.show_bookmarks.data,
            show_selections=form.show_selections.data,
            dont_clash_presentations=form.dont_clash_presentations.data,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        if (
            pclass_id != 0
            and len(project.project_classes.all()) == 0
            and not pclass.uses_supervisor
        ):
            project.project_classes.append(pclass)

        # ensure that list of preferred degree programmes is consistent
        project.validate_programmes()

        try:
            db.session.add(project)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add new project due to a database error. Please contact a system administrator",
                "error",
            )

        # auto-enroll if implied by current project class associations
        if not project.generic:
            owner = project.owner
            assert owner is not None

            for pclass in project.project_classes:
                if not owner.is_enrolled(pclass):
                    owner.add_enrollment(pclass)
                    flash(
                        "Auto-enrolled {name} in {pclass}".format(
                            name=project.owner.user.name, pclass=pclass.name
                        )
                    )

        if form.submit.data:
            return redirect(
                url_for(
                    "convenor.edit_descriptions",
                    id=project.id,
                    pclass_id=pclass_id,
                    create=1,
                )
            )
        elif form.save_and_exit.data:
            return redirect(url_for("convenor.attached", id=pclass_id))
        elif form.save_and_preview:
            return redirect(
                url_for(
                    "faculty.project_preview",
                    id=project.id,
                    text="attached projects list",
                    url=url_for("convenor.attached", id=pclass_id),
                )
            )
        else:
            raise RuntimeError("Unknown submit button in faculty.add_project")

    else:
        if request.method == "GET":
            # use convenor's defaults
            # This solution is arbitrary, but no more arbitrary than any other choice
            owner = current_user.faculty_data

            if owner is not None:
                if owner.show_popularity:
                    form.show_popularity.data = True
                    form.show_bookmarks.data = True
                    form.show_selections.data = True

                form.enforce_capacity.data = owner.enforce_capacity
                form.dont_clash_presentations.data = owner.dont_clash_presentations

            else:
                form.show_popularity.data = True
                form.show_bookmarks.data = True
                form.show_selections.data = False

                form.enforce_capacity.data = True
                form.dont_clash_presentations.data = True

    return render_template_context(
        "faculty/edit_project.html",
        project_form=form,
        pclass_id=pclass_id,
        title="Add new project",
        submit_url=url_for("convenor.add_project", pclass_id=pclass_id),
    )


@convenor.route("/edit_project/<int:id>/<int:pclass_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_project(id, pclass_id):
    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)
    if url is None:
        if pclass_id > 0:
            url = url_for("convenor.attached", id=pclass_id)
            text = "attached projects view"
        else:
            url = redirect_url()
            text = "previous view"

    # set up form
    project: Project = Project.query.get_or_404(id)

    EditProjectForm = EditProjectFormFactory(
        pclass.tenant if pclass is not None else current_user.tenants.all(),
        convenor_editing=True,
        uses_tags=True,
        uses_research_groups=True,
    )
    form = EditProjectForm(obj=project)
    form.project = project

    if form.validate_on_submit():
        allowed_tenants = [pclass.tenant]
        tag_list = create_new_tags(form, allowed_tenants)

        project.name = form.name.data
        project.ATAS_restricted = form.ATAS_restricted.data
        project.owner = form.owner.data if not form.generic.data else None
        project.generic = form.generic.data
        project.tags = tag_list
        project.group = form.group.data
        project.project_classes = form.project_classes.data
        project.meeting_reqd = form.meeting_reqd.data
        project.enforce_capacity = form.enforce_capacity.data
        project.show_popularity = form.show_popularity.data
        project.show_bookmarks = form.show_bookmarks.data
        project.show_selections = form.show_selections.data
        project.dont_clash_presentations = form.dont_clash_presentations.data
        project.last_edit_id = current_user.id
        project.last_edit_timestamp = datetime.now()

        if (
            pclass_id != 0
            and len(project.project_classes.all()) == 0
            and not pclass.uses_supervisor
        ):
            project.project_classes.append(pclass)

        # ensure that list of preferred degree programmes is now consistent
        project.validate_programmes()

        try:
            db.session.commit()

            # auto-enroll if implied by current project class associations
            if not project.generic:
                for pclass in project.project_classes:
                    assert project.owner is not None

                    if not project.owner.is_enrolled(pclass):
                        project.owner.add_enrollment(pclass)
                        flash(
                            "Auto-enrolled {name} in {pclass}".format(
                                name=project.owner.user.name, pclass=pclass.name
                            )
                        )

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes to project due to a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "faculty/edit_project.html",
        project_form=form,
        project=project,
        pclass_id=pclass_id,
        title="Edit library project details",
        url=url,
        text=text,
        submit_url=url_for(
            "convenor.edit_project",
            id=project.id,
            pclass_id=pclass_id,
            url=url,
            text=text,
        ),
    )


@convenor.route("/duplicate_project/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def duplicate_project(id):
    # id labels a Project instance
    proj: Project = Project.query.get_or_404(id)

    # ensure logged-in user is a convenor or other validated admin user
    if not validate_is_admin_or_convenor():
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    pclass_id = int(request.args.get("pclass_id", 0))

    if url is None:
        if pclass_id > 0:
            url = url_for("convenor.attached", id=pclass_id)
            text = "attached projects view"
        else:
            url = redirect_url()
            text = "previous view"

    # set up form
    allowed_tenants = [p.tenant for p in proj.project_classes]
    DuplicateProjectForm = DuplicateProjectFormFactory(allowed_tenants)
    form = DuplicateProjectForm(obj=proj)
    form.project = proj

    if form.validate_on_submit():
        tag_list = create_new_tags(form, allowed_tenants)

        new_proj = Project(
            name=form.name.data,
            active=True,
            owner=form.owner.data if not form.generic.data else None,
            generic=form.generic.data,
            ATAS_restricted=form.ATAS_restricted.data,
            tags=tag_list,
            group=form.group.data,
            project_classes=form.project_classes.data,
            meeting_reqd=form.meeting_reqd.data,
            enforce_capacity=form.enforce_capacity.data,
            show_popularity=form.show_popularity.data,
            show_bookmarks=form.show_bookmarks.data,
            show_selections=form.show_selections.data,
            dont_clash_presentations=form.dont_clash_presentations.data,
            last_edit_id=None,
            last_edit_timestamp=None,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        new_proj.default_id = None

        # copy attached roles and alternative projects
        new_proj.assessors = proj.assessors
        new_proj.supervisors = proj.supervisors
        new_proj.alternatives = proj.alternatives

        new_proj.skills = proj.skills
        new_proj.programmes = proj.programmes

        try:
            db.session.add(new_proj)
            db.session.flush()

            # duplicate attached descriptions
            for desc in proj.descriptions:
                desc: ProjectDescription

                new_desc = ProjectDescription()
                for item in [
                    p.key for p in class_mapper(ProjectDescription).iterate_properties
                ]:
                    if item not in ["id", "parent_id"]:
                        setattr(new_desc, item, getattr(desc, item))

                    new_desc.parent_id = new_proj.id

                    db.session.add(new_desc)

            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not duplicate project due to a database error. Please contact a system administrator",
                "error",
            )

        else:
            flash(f'Successfully duplicated project as "{new_proj.name}"', "success")

        return redirect(url)

    else:
        if request.method == "GET":
            form.name.date = None

    return render_template_context(
        "faculty/edit_project.html",
        project_form=form,
        pclass_id=pclass_id,
        title="Duplicate library project",
        url=url,
        text=text,
        submit_url=url_for(
            "convenor.duplicate_project",
            id=proj.id,
            pclass_id=pclass_id,
            url=url,
            text=text,
        ),
    )


@convenor.route("/activate_project/<int:id>/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def activate_project(id, pclass_id):
    # get project details
    proj: Project = Project.query.get_or_404(id)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

    proj.enable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not activate project due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/deactivate_project/<int:id>/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def deactivate_project(id, pclass_id):
    # get project details
    proj = Project.query.get_or_404(id)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

    # if logged-in user is not a suitable convenor, or an administrator, object
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    proj.disable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not deactivate project due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/add_description/<int:pid>/<int:pclass_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def add_description(pid, pclass_id):
    # get project details
    proj = Project.query.get_or_404(pid)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

    create = request.args.get("create", default=None)

    AddDescriptionForm = AddDescriptionFormFactory(pid)
    form = AddDescriptionForm(request.form)
    form.project_id = pid

    if form.validate_on_submit():
        data = ProjectDescription(
            parent_id=pid,
            label=form.label.data,
            project_classes=form.project_classes.data,
            description=None,
            reading=None,
            aims=form.aims.data,
            team=form.team.data,
            capacity=form.capacity.data,
            review_only=form.review_only.data,
            confirmed=False,
            workflow_state=WorkflowMixin.WORKFLOW_APPROVAL_QUEUED,
            validator_id=None,
            validated_timestamp=None,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            db.session.add(data)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add new project description due to a database error. Please contact a system administrator",
                "error",
            )

        return redirect(
            url_for(
                "convenor.edit_descriptions", id=pid, pclass_id=pclass_id, create=create
            )
        )

    return render_template_context(
        "faculty/edit_description.html",
        project=proj,
        form=form,
        pclass_id=pclass_id,
        title="Add new description",
        create=create,
        unique_id=uuid4(),
    )


@convenor.route("/edit_description/<int:did>/<int:pclass_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_description(did, pclass_id):
    desc = ProjectDescription.query.get_or_404(did)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        if not validate_edit_description(desc):
            return redirect(redirect_url())

    create = request.args.get("create", default=None)
    url = request.args.get("url", None)
    text = request.args.get("text", None)
    if url is None:
        url = url_for(
            "convenor.edit_descriptions",
            id=desc.parent_id,
            pclass_id=pclass_id,
            create=create,
        )
        text = "project variants list"

    EditDescriptionForm = EditDescriptionSettingsFormFactory(desc.parent_id, did)
    form = EditDescriptionForm(obj=desc)
    form.project_id = desc.parent_id
    form.desc = desc

    if form.validate_on_submit():
        desc.label = form.label.data
        desc.project_classes = form.project_classes.data
        desc.aims = form.aims.data
        desc.team = form.team.data
        desc.capacity = form.capacity.data
        desc.review_only = form.review_only.data
        desc.last_edit_id = current_user.id
        desc.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not edit project description due to a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "faculty/edit_description.html",
        project=desc.parent,
        desc=desc,
        form=form,
        pclass_id=pclass_id,
        title="Edit description",
        create=create,
        url=url,
        text=text,
    )


@convenor.route(
    "/edit_description_content/<int:did>/<int:pclass_id>", methods=["GET", "POST"]
)
@roles_accepted("faculty", "admin", "root")
def edit_description_content(did, pclass_id):
    desc = ProjectDescription.query.get_or_404(did)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        if not validate_edit_description(desc):
            return redirect(redirect_url())

    create = request.args.get("create", default=None)
    url = request.args.get("url", None)
    text = request.args.get("text", None)
    if url is None:
        url = url_for(
            "convenor.edit_descriptions",
            id=desc.parent_id,
            pclass_id=pclass_id,
            create=create,
        )
        text = "project variants list"

    form = EditDescriptionContentForm(obj=desc)

    if form.validate_on_submit():
        desc.description = form.description.data
        desc.reading = form.reading.data
        desc.last_edit_id = current_user.id
        desc.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not edit project description due to a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "faculty/edit_description_content.html",
        project=desc.parent,
        desc=desc,
        form=form,
        pclass_id=pclass_id,
        title="Edit description",
        create=create,
        url=url,
        text=text,
    )


@convenor.route(
    "/description_modules/<int:did>/<int:pclass_id>/<int:level_id>",
    methods=["GET", "POST"],
)
@convenor.route(
    "/description_modules/<int:did>/<int:pclass_id>", methods=["GET", "POST"]
)
@roles_accepted("faculty", "admin", "root")
def description_modules(did, pclass_id, level_id=None):
    desc = ProjectDescription.query.get_or_404(did)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_edit_description(desc):
            return redirect(redirect_url())

    create = request.args.get("create", default=None)

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
        modules = desc.get_available_modules(level_id=form.selector.data.id)
    else:
        modules = []

    level_id = form.selector.data.id if form.selector.data is not None else None
    levels = (
        FHEQ_Level.query.filter_by(active=True)
        .order_by(FHEQ_Level.numeric_level.asc())
        .all()
    )

    return render_template_context(
        "convenor/projects/description_modules.html",
        project=desc.parent,
        desc=desc,
        form=form,
        pclass_id=pclass_id,
        title="Attach recommended modules",
        levels=levels,
        create=create,
        modules=modules,
        level_id=level_id,
    )


@convenor.route(
    "/description_attach_module/<int:did>/<int:pclass_id>/<int:mod_id>/<int:level_id>"
)
@roles_accepted("faculty", "admin", "root")
def description_attach_module(did, pclass_id, mod_id, level_id):
    desc: ProjectDescription = ProjectDescription.query.get_or_404(did)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_edit_description(desc):
            return redirect(redirect_url())

    create = request.args.get("create", default=None)
    module: Module = Module.query.get_or_404(mod_id)

    if desc.module_available(module.id):
        if module not in desc.modules:
            desc.modules.append(module)

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                flash(
                    'Could not attach module "{name}" due to a database error. '
                    "Please contact a system administrator".format(name=module.name),
                    "error",
                )

        else:
            flash(
                'Could not attach module "{name}" because it is already attached.'.format(
                    name=module.name
                ),
                "warning",
            )

    else:
        flash(
            'Could not attach module "{name}" because it cannot be applied as a pre-requisite '
            "for this description. Most likely this means it is incompatible with one of the selected "
            "project classes. Consider generating a new variant for the incompatible "
            "classes.".format(name=module.name),
            "warning",
        )

    return redirect(
        url_for(
            "convenor.description_modules",
            did=did,
            pclass_id=pclass_id,
            level_id=level_id,
            create=create,
        )
    )


@convenor.route(
    "/description_detach_module/<int:did>/<int:pclass_id>/<int:mod_id>/<int:level_id>"
)
@roles_accepted("faculty", "admin", "root")
def description_detach_module(did, pclass_id, mod_id, level_id):
    desc: ProjectDescription = ProjectDescription.query.get_or_404(did)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_edit_description(desc):
            return redirect(redirect_url())

    create = request.args.get("create", default=None)
    module: Module = Module.query.get_or_404(mod_id)

    if module in desc.modules:
        desc.modules.remove(module)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                'Could not detach module "{name}" due to a database error. '
                "Please contact a system administrator".format(name=module.name),
                "error",
            )

    else:
        flash(
            'Could not detach specified module "{name}" because it was not previously '
            "attached.".format(name=module.name),
            "warning",
        )

    return redirect(
        url_for(
            "convenor.description_modules",
            did=did,
            pclass_id=pclass_id,
            level_id=level_id,
            create=create,
        )
    )


@convenor.route("/delete_description/<int:did>/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def delete_description(did, pclass_id):
    desc = ProjectDescription.query.get_or_404(did)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_edit_description(desc):
            return redirect(redirect_url())

    try:
        db.session.delete(desc)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not delete project description due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/duplicate_description/<int:did>/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def duplicate_description(did, pclass_id):
    desc = ProjectDescription.query.get_or_404(did)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_edit_description(desc):
            return redirect(redirect_url())

    suffix = 2
    while suffix < 100:
        new_label = "{label} #{suffix}".format(label=desc.label, suffix=suffix)

        if (
            ProjectDescription.query.filter_by(
                parent_id=desc.parent_id, label=new_label
            ).first()
            is None
        ):
            break

        suffix += 1

    if suffix >= 100:
        flash(
            'Could not duplicate variant "{label}" because a new unique label could not '
            "be generated".format(label=desc.label),
            "error",
        )
        return redirect(redirect_url())

    data = ProjectDescription(
        parent_id=desc.parent_id,
        label=new_label,
        project_classes=[],
        modules=[],
        capacity=desc.capacity,
        description=desc.description,
        reading=desc.reading,
        team=desc.team,
        confirmed=False,
        workflow_state=WorkflowMixin.WORKFLOW_APPROVAL_QUEUED,
        validator_id=None,
        validated_timestamp=None,
        creator_id=current_user.id,
        creation_timestamp=datetime.now(),
    )

    try:
        db.session.add(data)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not duplicate project description due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/move_description/<int:did>/<int:pclass_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def move_description(did, pclass_id):
    desc = ProjectDescription.query.get_or_404(did)
    old_project = desc.parent

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_edit_description(desc):
            return redirect(redirect_url())

    create = request.args.get("create", default=None)

    MoveDescriptionForm = MoveDescriptionFormFactory(
        old_project.owner_id, old_project.id, pclass_id=pclass_id
    )
    form = MoveDescriptionForm(request.form)

    if form.validate_on_submit():
        new_project = form.destination.data
        leave_copy = form.copy.data

        if new_project is not None:
            if leave_copy:
                copy_desc = ProjectDescription(
                    parent_id=desc.parent.id,
                    label=desc.label,
                    description=desc.description,
                    reading=desc.reading,
                    team=desc.team,
                    project_classes=desc.project_classes,
                    modules=desc.modules,
                    capacity=desc.capacity,
                    confirmed=False,
                    workflow_state=desc.workflow_state,
                    validator_id=desc.validator_id,
                    validated_timestamp=desc.validated_timestamp,
                    creator_id=current_user.id,
                    creation_timestamp=datetime.now(),
                )
            else:
                copy_desc = None

            # relabel project if needed
            labels = get_count(new_project.descriptions.filter_by(label=desc.label))
            if labels > 0:
                desc.label = "{old} #{n}".format(old=desc.label, n=labels + 1)

            # remove subscription to any project classes that are already subscribed
            remove = set()

            for pclass in desc.project_classes:
                if get_count(new_project.project_classes.filter_by(id=pclass.id)) == 0:
                    remove.add(pclass)

                elif (
                    get_count(
                        new_project.descriptions.filter(
                            ProjectDescription.project_classes.any(id=pclass.id)
                        )
                    )
                    > 0
                ):
                    remove.add(pclass)

            for pclass in remove:
                desc.project_classes.remove(pclass)

            if old_project.default_id is not None and old_project.default_id == desc.id:
                old_project.default_id = None

            desc.parent_id = new_project.id
            if copy_desc is not None:
                db.session.add(copy_desc)

            try:
                db.session.commit()
                flash(
                    'Variant "{name}" successfully moved to project "{pname}"'.format(
                        name=desc.label, pname=new_project.name
                    ),
                    "info",
                )
            except SQLAlchemyError as e:
                db.session.rollback()
                flash(
                    'Variant "{name}" could not be moved due to a database error'.format(
                        name=desc.label
                    ),
                    "error",
                )
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        else:
            flash(
                'Variant "{name}" could not be moved because its parent project is '
                "missing".format(name=desc.label),
                "error",
            )

        if create:
            return redirect(
                url_for(
                    "convenor.edit_descriptions",
                    id=old_project.id,
                    pclass_id=pclass_id,
                    create=True,
                )
            )
        else:
            return redirect(
                url_for(
                    "convenor.edit_descriptions", id=new_project.id, pclass_id=pclass_id
                )
            )

    return render_template_context(
        "faculty/move_description.html",
        form=form,
        desc=desc,
        pclass_id=pclass_id,
        create=create,
        title='Move "{name}" to a new project'.format(name=desc.label),
    )


@convenor.route("/make_default_description/<int:pid>/<int:pclass_id>/<int:did>")
@convenor.route("/make_default_description/<int:pid>/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def make_default_description(pid, pclass_id, did=None):
    proj = Project.query.get_or_404(pid)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

    if did is not None:
        desc = ProjectDescription.query.get_or_404(did)

        if desc.parent_id != pid:
            flash(
                "Cannot set default description (id={did}) for project (id={pid}) because this description "
                "does not belong to the project".format(pid=pid, did=did),
                "error",
            )
            return redirect(redirect_url())

    proj.default_id = did
    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/attach_skills/<int:id>/<int:pclass_id>/<int:sel_id>")
@convenor.route("/attach_skills/<int:id>/<int:pclass_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def attach_skills(id, pclass_id, sel_id=None):
    # get project details
    proj = Project.query.get_or_404(id)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

    form = SkillSelectorForm(request.form)

    if not form.validate_on_submit() and request.method == "GET":
        if sel_id is None:
            form.selector.data = (
                SkillGroup.query.filter(SkillGroup.active.is_(True))
                .order_by(SkillGroup.name.asc())
                .first()
            )
        else:
            form.selector.data = SkillGroup.query.filter(
                SkillGroup.active.is_(True), SkillGroup.id == sel_id
            ).first()

    # get list of active skills matching selector
    if form.selector.data is not None:
        skills = TransferableSkill.query.filter(
            TransferableSkill.active.is_(True),
            TransferableSkill.group_id == form.selector.data.id,
        ).order_by(TransferableSkill.name.asc())
    else:
        skills = TransferableSkill.query.filter_by(active=True).order_by(
            TransferableSkill.name.asc()
        )

    create = request.args.get("create", default=None)

    return render_template_context(
        "convenor/projects/attach_skills.html",
        data=proj,
        skills=skills,
        pclass_id=pclass_id,
        form=form,
        sel_id=form.selector.data.id,
        create=create,
    )


@convenor.route("/add_skill/<int:projectid>/<int:skillid>/<int:pclass_id>/<int:sel_id>")
@roles_accepted("faculty", "admin", "root")
def add_skill(projectid, skillid, pclass_id, sel_id):
    # get project details
    proj = Project.query.get_or_404(projectid)

    # if project owner is not logged-in user or a suitable convenor, or an administrator, object
    if not validate_edit_project(proj):
        return redirect(redirect_url())

    create = request.args.get("create", default=None)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill not in proj.skills:
        proj.add_skill(skill)
        db.session.commit()

    return redirect(
        url_for(
            "convenor.attach_skills",
            id=projectid,
            pclass_id=pclass_id,
            sel_id=sel_id,
            create=create,
        )
    )


@convenor.route(
    "/remove_skill/<int:projectid>/<int:skillid>/<int:pclass_id>/<int:sel_id>"
)
@roles_accepted("faculty", "admin", "root")
def remove_skill(projectid, skillid, pclass_id, sel_id):
    # get project details
    proj = Project.query.get_or_404(projectid)

    # if project owner is not logged-in user or a suitable convenor, or an administrator, object
    if not validate_edit_project(proj):
        return redirect(redirect_url())

    create = request.args.get("create", default=None)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill in proj.skills:
        proj.remove_skill(skill)
        db.session.commit()

    return redirect(
        url_for(
            "convenor.attach_skills",
            id=projectid,
            pclass_id=pclass_id,
            sel_id=sel_id,
            create=create,
        )
    )


@convenor.route("/attach_programmes/<int:id>/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def attach_programmes(id, pclass_id):
    # get project details
    proj = Project.query.get_or_404(id)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

    q = proj.available_degree_programmes

    create = request.args.get("create", default=None)

    return render_template_context(
        "convenor/projects/attach_programmes.html",
        data=proj,
        programmes=q.all(),
        pclass_id=pclass_id,
        create=create,
    )


@convenor.route("/add_programme/<int:id>/<int:pclass_id>/<int:prog_id>")
@roles_accepted("faculty", "admin", "root")
def add_programme(id, pclass_id, prog_id):
    # get project details
    proj = Project.query.get_or_404(id)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

    programme = DegreeProgramme.query.get_or_404(prog_id)

    if proj.programmes is not None and programme not in proj.programmes:
        proj.add_programme(programme)
        db.session.commit()

    return redirect(redirect_url())


@convenor.route("/remove_programme/<int:id>/<int:pclass_id>/<int:prog_id>")
@roles_accepted("faculty", "admin", "root")
def remove_programme(id, pclass_id, prog_id):
    # get project details
    proj = Project.query.get_or_404(id)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

    programme = DegreeProgramme.query.get_or_404(prog_id)

    if proj.programmes is not None and programme in proj.programmes:
        proj.remove_programme(programme)
        db.session.commit()

    return redirect(redirect_url())


@convenor.route("/attach_assessors/<int:id>/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def attach_assessors(id, pclass_id):
    # get project details
    proj = Project.query.get_or_404(id)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

    url = request.args.get("url")
    text = request.args.get("text")

    create = request.args.get("create", default=None)

    # DISCOVER APPLIED FILTERS

    state_filter = request.args.get("state_filter")
    pclass_filter = request.args.get("pclass_filter")
    group_filter = request.args.get("group_filter")

    # if no state filter supplied, check if one is stored in session
    if state_filter is None and session.get("convenor_marker_state_filter"):
        state_filter = session["convenor_marker_state_filter"]

    # if no pclass filter supplied, check if one is stored in session
    if pclass_filter is None and session.get("convenor_marker_pclass_filter"):
        pclass_filter = session["convenor_marker_pclass_filter"]

    # if no group filter supplied, check if one is stored in session
    if group_filter is None and session.get("convenor_marker_group_filter"):
        group_filter = session["convenor_marker_group_filter"]

    # GET ALLOWED PROJECT CLASSES CLASSES

    # get list of project classes to which this project is attached, and which require assignment of
    # second markers
    pclasses: List[ProjectClass] = proj.project_classes.filter(
        and_(
            ProjectClass.active.is_(True),
            or_(
                ProjectClass.uses_marker.is_(True),
                ProjectClass.uses_presentations.is_(True),
            ),
        )
    ).all()

    pcl_list = []
    pclass_filter_allowed = ["all"]
    for pcl in pclasses:
        pcl: ProjectClass

        # get current configuration record for this project class
        config: ProjectClassConfig = pcl.most_recent_config
        if config is None:
            flash(
                "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
                "error",
            )
            return redirect(redirect_url())

        pcl_list.append((pcl, config))
        pclass_filter_allowed.append(str(pcl.id))

    # GET ALLOWED RESEARCH GROUPS

    # get list of available research groups
    groups: List[ResearchGroup] = ResearchGroup.query.filter_by(active=True).all()

    group_filter_allowed = ["all"]
    for g in groups:
        g: ResearchGroup
        group_filter_allowed.append(str(g.id))

    # VALIDATE FILTERS

    # if no filter is set, and there is only one allowed project class, default to that class
    if pclass_filter is None and len(pclass_filter_allowed) == 1:
        pclass_filter = str(pclass_filter_allowed[0])

    if pclass_filter not in pclass_filter_allowed:
        pclass_filter = "all"

    if state_filter not in ["all", "attached", "not-attached"]:
        state_filter = "all"

    if group_filter not in group_filter_allowed:
        group_filter = "all"

    # CACHE FILTERS

    # write pclass filter into session if it is not empty
    if pclass_filter is not None:
        session["convenor_marker_pclass_filter"] = pclass_filter

    # write state filter into session if it is not empty
    if state_filter is not None:
        session["convenor_marker_state_filter"] = state_filter

    # write group filter into session if it is not empty
    if group_filter is not None:
        session["convenor_marker_group_filter"] = group_filter

    return render_template_context(
        "convenor/projects/attach_assessors.html",
        data=proj,
        pclass_id=pclass_id,
        groups=groups,
        pclasses=pcl_list,
        state_filter=state_filter,
        pclass_filter=pclass_filter,
        group_filter=group_filter,
        create=create,
        url=url,
        text=text,
    )


@convenor.route("/attach_assessors_ajax/<int:id>/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def attach_assessors_ajax(id, pclass_id):
    # get project details
    proj: Project = Project.query.get_or_404(id)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return jsonify({})

    else:
        # get project class details
        pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return jsonify({})

    state_filter = request.args.get("state_filter")
    pclass_filter = request.args.get("pclass_filter")
    group_filter = request.args.get("group_filter")

    faculty = filter_assessors(proj, state_filter, pclass_filter, group_filter)

    return ajax.project.build_assessor_data(
        faculty,
        proj,
        _marker_menu,
        pclass_id=pclass_id,
        url=url_for(
            "convenor.attach_assessors",
            id=id,
            pclass_id=pclass_id,
            url=url_for("convenor.attached", id=pclass_id),
            text="convenor dashboard",
        ),
    )


@convenor.route("/add_assessor/<int:proj_id>/<int:pclass_id>/<int:mid>")
@roles_accepted("faculty", "admin", "root")
def add_assessor(proj_id, pclass_id, mid):
    # get project details
    proj: Project = Project.query.get_or_404(proj_id)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

    assessor = FacultyData.query.get_or_404(mid)

    proj.add_assessor(assessor, autocommit=True)

    return redirect(redirect_url())


@convenor.route("/remove_assessor/<int:proj_id>/<int:pclass_id>/<int:mid>")
@roles_accepted("faculty", "admin", "root")
def remove_assessor(proj_id, pclass_id, mid):
    # get project details
    proj: Project = Project.query.get_or_404(proj_id)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

    assessor = FacultyData.query.get_or_404(mid)

    proj.remove_assessor(assessor, autocommit=True)

    return redirect(redirect_url())


@convenor.route("/attach_all_assessors/<int:proj_id>/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def attach_all_assessors(proj_id, pclass_id):
    # get project details
    proj: Project = Project.query.get_or_404(proj_id)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

    state_filter = request.args.get("state_filter")
    pclass_filter = request.args.get("pclass_filter")
    group_filter = request.args.get("group_filter")

    assessors = filter_assessors(proj, state_filter, pclass_filter, group_filter)

    for assessor in assessors:
        proj.add_assessor(assessor, autocommit=False)

    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/remove_all_assessors/<int:proj_id>/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def remove_all_assessors(proj_id, pclass_id):
    # get project details
    proj: Project = Project.query.get_or_404(proj_id)

    if pclass_id == 0:
        # got here from unattached projects view; reject if user is not administrator
        if not validate_is_administrator():
            return redirect(redirect_url())

    else:
        # get project class details
        pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

        # if logged-in user is not a suitable convenor, or an administrator, object
        if not validate_is_convenor(pclass):
            return redirect(redirect_url())

    state_filter = request.args.get("state_filter")
    pclass_filter = request.args.get("pclass_filter")
    group_filter = request.args.get("group_filter")

    assessors = filter_assessors(proj, state_filter, pclass_filter, group_filter)

    for assessor in assessors:
        proj.remove_assessor(assessor, autocommit=False)

    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/liveproject_sync_assessors/<int:proj_id>/<int:live_id>")
@roles_accepted("faculty", "admin", "root")
def liveproject_sync_assessors(proj_id, live_id):
    # get library project
    library_project: Project = Project.query.get_or_404(proj_id)

    # get liveproject
    live_project: LiveProject = LiveProject.query.get_or_404(live_id)
    # get project class details

    # if logged-in user is not a suitable convenor, or an administrator, object
    if not validate_is_convenor(live_project.config.project_class):
        return redirect(redirect_url())

    # copy assessors from library project to live project, if they are current
    live_project.assessors = [
        f for f in library_project.assessors if library_project.is_assessor(f.id)
    ]
    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/liveproject_attach_assessor/<int:live_id>/<int:fac_id>")
@roles_accepted("faculty", "admin", "root")
def liveproject_attach_assessor(live_id, fac_id):
    # get liveproject
    live_project: LiveProject = LiveProject.query.get_or_404(live_id)
    # get project class details

    # if logged-in user is not a suitable convenor, or an administrator, object
    if not validate_is_convenor(live_project.config.project_class):
        return redirect(redirect_url())

    faculty: FacultyData = FacultyData.query.get_or_404(fac_id)

    if faculty not in live_project.assessors:
        live_project.assessors.append(faculty)
        db.session.commit()

    return redirect(redirect_url())


@convenor.route("/liveproject_remove_assessor/<int:live_id>/<int:fac_id>")
@roles_accepted("faculty", "admin", "root")
def liveproject_remove_assessor(live_id, fac_id):
    # get liveproject
    live_project: LiveProject = LiveProject.query.get_or_404(live_id)
    # get project class details

    # if logged-in user is not a suitable convenor, or an administrator, object
    if not validate_is_convenor(live_project.config.project_class):
        return redirect(redirect_url())

    fd = FacultyData.query.get_or_404(fac_id)

    if fd in live_project.assessors:
        live_project.assessors.remove(fd)
        db.session.commit()

    return redirect(redirect_url())
