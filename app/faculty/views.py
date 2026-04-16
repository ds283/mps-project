#
# Created by David Seery on 15/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import date, datetime
from typing import Dict, List

from flask import current_app, flash, jsonify, redirect, request, session, url_for
from flask_security import current_user, roles_accepted, roles_required
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.local import LocalProxy

import app.ajax as ajax

from ..admin.forms import LevelSelectorForm
from ..campaigns import check_2026_ATAS
from ..database import db
from ..models import (
    DegreeProgramme,
    DescriptionComment,
    EmailTemplate,
    EmailWorkflow,
    EmailWorkflowItem,
    EnrollmentRecord,
    FacultyData,
    FHEQ_Level,
    LiveMarkingScheme,
    LiveProject,
    MainConfig,
    MarkingEvent,
    MarkingReport,
    MarkingWorkflow,
    ModeratorReport,
    MessageOfTheDay,
    Module,
    PresentationAssessment,
    PresentationSession,
    Project,
    ProjectClass,
    ProjectClassConfig,
    ProjectDescription,
    ProjectDescriptionWorkflowHistory,
    ResearchGroup,
    ScheduleSlot,
    SelectingStudent,
    SkillGroup,
    StudentData,
    StudentJournalEntry,
    SubmissionPeriodRecord,
    SubmissionRecord,
    SubmissionRole,
    SubmittingStudent,
    Tenant,
    TransferableSkill,
    User,
    WorkflowMixin,
)
from ..models.emails import encode_email_payload
from ..models.submissions import SubmissionRoleTypesMixin
from ..shared.actions import (
    do_cancel_confirm,
    do_confirm,
    do_deconfirm_to_pending,
    render_project,
)
from ..shared.context.global_context import render_template_context
from ..shared.context.root_dashboard import get_root_dashboard_data
from ..shared.conversions import is_integer
from ..shared.projects import create_new_tags, project_list_SQL_handler
from ..shared.utils import (
    allow_approval_for_description,
    filter_assessors,
    get_approval_queue_data,
    get_count,
    get_current_year,
    get_main_config,
    home_dashboard,
    redirect_url,
)
from ..shared.validators import (
    validate_assessment,
    validate_edit_description,
    validate_edit_project,
    validate_is_convenor,
    validate_is_project_owner,
    validate_presentation_assessor,
    validate_project_open,
    validate_submission_role,
    validate_submission_supervisor,
    validate_submission_viewable,
    validate_using_assessment,
    validate_view_project,
)
from ..shared.workflow_logging import log_db_commit
from . import faculty
from .forms import (
    AddDescriptionFormFactory,
    AddProjectFormFactory,
    ApproveMarkingReportForm,
    AvailabilityFormFactory,
    EditDescriptionContentForm,
    EditDescriptionSettingsFormFactory,
    EditProjectFormFactory,
    FacultyPreviewFormFactory,
    FacultySettingsFormFactory,
    MoveDescriptionFormFactory,
    SkillSelectorForm,
    SubmissionRoleFeedbackForm,
    SubmissionRoleResponseForm,
)

_security = LocalProxy(lambda: current_app.extensions["security"])
_datastore = LocalProxy(lambda: _security.datastore)


# language=jinja2
_marker_menu = """
{% if proj.is_assessor(f.id) %}
    <a href="{{ url_for('faculty.remove_assessor', proj_id=proj.id, mid=f.id) }}"
       class="btn btn-sm full-width-button btn-secondary">
        <i class="fas fa-trash"></i> Remove
    </a>
{% elif proj.can_enroll_assessor(f) %}
    <a href="{{ url_for('faculty.add_assessor', proj_id=proj.id, mid=f.id) }}"
       class="btn btn-sm full-width-button btn-secondary">
        <i class="fas fa-plus"></i> Attach
    </a>
{% else %}
    <a class="btn btn-secondary full-width-button btn-sm disabled">
        <i class="fas fa-ban"></i> Can't attach
    </a>
{% endif %}
"""


# label for project description list
# language=jinja2
_desc_label = """
{% set valid = not d.has_issues %}
{% if not valid %}
    <i class="fas fa-exclamation-triangle text-danger"></i>
{% endif %}
<a class="text-decoration-none" href="{{ url_for('faculty.project_preview', id=d.parent.id, pclass=desc_pclass_id,
                    url=url_for('faculty.edit_descriptions', id=d.parent.id, create=create),
                    text='description list view') }}">
    {{ d.label }}
</a>
<div>
    {% if d.review_only %}
        <span class="badge bg-info">Review project</span>
    {% endif %}
</div>
{% set state = d.workflow_state %}
<div>
    {% set not_confirmed = d.requires_confirmation and not d.confirmed %}
    {% if not_confirmed %}
        <span class="badge bg-secondary">Approval: Not confirmed</span>
    {% else %}
        {% if state == d.WORKFLOW_APPROVAL_VALIDATED %}
            <span class="badge bg-success"><i class="fas fa-check"></i>Approved</span>
        {% elif state == d.WORKFLOW_APPROVAL_QUEUED %}
            <span class="badge bg-warning text-dark">Approval: Confirmed</span>
        {% elif state == d.WORKFLOW_APPROVAL_REJECTED %}
            <span class="badge bg-info">Approval: In progress</span>
        {% else %}
            <span class="badge bg-danger">Approval: unknown state</span>
        {% endif %}
        {% if state == d.WORKFLOW_APPROVAL_VALIDATED and current_user.has_role('project_approver') and d.validated_by %}
            <div>
                <span class="badge bg-info">Signed-off: {{ d.validated_by.name }}</span>
                {% if d.validated_timestamp %}
                    <span class="badge bg-info">{{ d.validated_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}</span>
                {% endif %}
            </div>
        {% endif %}
    {% endif %}
    {% if d.has_new_comments(current_user) %}
        <div>
            <span class="badge bg-warning text-dark">New comments</span>
        </div>
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
           url=url_for('faculty.edit_descriptions', id=d.parent.id, create=create),
           text='description list view') }}">
            <i class="fas fa-search fa-fw"></i> Preview web page
        </a>

        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Edit description</div>

        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.edit_description', did=d.id, create=create,
                                                  url=url_for('faculty.edit_descriptions', id=d.parent_id, create=create),
                                                  text='project variants list') }}">
            <i class="fas fa-sliders-h fa-fw"></i> Settings...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.edit_description_content', did=d.id, create=create,
                                                  url=url_for('faculty.edit_descriptions', id=d.parent_id, create=create),
                                                  text='project variants list') }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit content...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.description_modules', did=d.id, create=create) }}">
            <i class="fas fa-cogs fa-fw"></i> Recommended modules...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.duplicate_description', did=d.id) }}">
            <i class="fas fa-clone fa-fw"></i> Duplicate
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.move_description', did=d.id, create=create) }}">
            <i class="fas fa-folder-open fa-fw"></i> Move to project...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.delete_description', did=d.id) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
        
        <div role="separator" class="dropdown-divider"></div>
        
        {% if d.default is none %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.make_default_description', pid=d.parent_id, did=d.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make default
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.make_default_description', pid=d.parent_id) }}">
                <i class="fas fa-wrench fa-fw"></i> Remove default
            </a>
        {% endif %}
    </div>
</div>
"""


@faculty.route("/affiliations")
@roles_required("faculty")
def affiliations():
    """
    Allow a faculty member to adjust their own affiliations without admin privileges
    :return:
    """

    data: FacultyData = FacultyData.query.get_or_404(current_user.id)

    user_tenant_ids: List[int] = [t.id for t in current_user.tenants]

    research_groups: List[ResearchGroup] = (
        ResearchGroup.query.filter(
            ResearchGroup.active.is_(True),
            ResearchGroup.tenants.any(Tenant.id.in_(user_tenant_ids)),
        )
        .order_by(ResearchGroup.name)
        .all()
    )

    return render_template_context(
        "faculty/affiliations.html",
        user=current_user,
        data=data,
        research_groups=research_groups,
    )


@faculty.route("/add_affiliation/<int:groupid>")
@roles_required("faculty")
def add_affiliation(groupid):
    data: FacultyData = FacultyData.query.get_or_404(current_user.id)
    group: ResearchGroup = ResearchGroup.query.get_or_404(groupid)

    if not data.has_affiliation(group):
        data.add_affiliation(group, autocommit=True)

    return redirect(redirect_url())


@faculty.route("/remove_affiliation/<int:groupid>")
@roles_required("faculty")
def remove_affiliation(groupid):
    data: FacultyData = FacultyData.query.get_or_404(current_user.id)
    group: ResearchGroup = ResearchGroup.query.get_or_404(groupid)

    if data.has_affiliation(group):
        data.remove_affiliation(group, autocommit=True)

    return redirect(redirect_url())


@faculty.route("/edit_projects")
@roles_required("faculty")
def edit_projects():
    groups = (
        SkillGroup.query.filter_by(active=True).order_by(SkillGroup.name.asc()).all()
    )

    state_filter = request.args.get("state_filter")

    if state_filter is None and session.get("project_library_state_filter"):
        state_filter = session["project_library_state_filter"]

    if state_filter not in ["all", "active", "not-active"]:
        state_filter = "active"

    session["project_library_state_filter"] = state_filter

    return render_template_context(
        "faculty/edit_projects.html", groups=groups, state_filter=state_filter
    )


@faculty.route("/projects_ajax", methods=["POST"])
@roles_required("faculty")
def projects_ajax():
    """
    AJAX endpoint for Edit Projects view
    :return:
    """

    base_query = db.session.query(Project).filter_by(owner_id=current_user.id)

    state_filter = request.args.get("state_filter")
    if state_filter not in ["all", "active", "not-active"]:
        state_filter = "all"

    if state_filter == "active":
        base_query = base_query.filter(Project.active)
    elif state_filter == "not-active":
        base_query = base_query.filter(~Project.active)

    return project_list_SQL_handler(
        request,
        base_query,
        current_user=current_user,
        menu_template="faculty",
        name_labels=True,
        text="projects list",
        url=url_for("faculty.edit_projects"),
        show_approvals=True,
        show_errors=True,
    )


@faculty.route("/assessor_for")
@roles_required("faculty")
def assessor_for():
    pclass_filter = request.args.get("pclass_filter")

    # if no pclass filter supplied, check if one is stored in session
    if pclass_filter is None and session.get("view_marker_pclass_filter"):
        pclass_filter = session["view_marker_pclass_filter"]

    # write pclass filter into session if it is not empty
    if pclass_filter is not None:
        session["view_marker_pclass_filter"] = pclass_filter

    groups = (
        SkillGroup.query.filter_by(active=True).order_by(SkillGroup.name.asc()).all()
    )
    pclasses = (
        ProjectClass.query.filter_by(active=True, publish=True)
        .order_by(ProjectClass.name.asc())
        .all()
    )

    return render_template_context(
        "faculty/assessor_for.html",
        groups=groups,
        pclasses=pclasses,
        pclass_filter=pclass_filter,
    )


@faculty.route("/marking_ajax", methods=["POST"])
@roles_required("faculty")
def marking_ajax():
    """
    AJAX endpoint for Assessor pool view
    :return:
    """
    pclass_filter = request.args.get("pclass_filter")
    flag, pclass_value = is_integer(pclass_filter)

    base_query = current_user.faculty_data.assessor_for
    if flag:
        base_query = base_query.filter(Project.project_classes.any(id=pclass_value))

    return project_list_SQL_handler(
        request,
        base_query,
        current_user=current_user,
        show_approvals=False,
        show_errors=False,
    )


@faculty.route("/edit_descriptions/<int:id>")
@roles_required("faculty")
def edit_descriptions(id):
    project = Project.query.get_or_404(id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(project):
        return redirect(redirect_url())

    create = request.args.get("create", default=None)

    missing_aims = [x for x in project.descriptions if x.has_warning("aims")]

    return render_template_context(
        "faculty/edit_descriptions.html",
        project=project,
        create=create,
        missing_aims=missing_aims,
    )


@faculty.route("/descriptions_ajax/<int:id>")
@roles_required("faculty")
def descriptions_ajax(id):
    project = Project.query.get_or_404(id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(project):
        return jsonify({})

    descs = project.descriptions.all()

    create = request.args.get("create", default=None)

    return ajax.faculty.descriptions_data(descs, _desc_label, _desc_menu, create=create)


def enrolled_for_pclasses_using_tags(fd: FacultyData):
    for item in fd.enrollments:
        item: EnrollmentRecord
        pclass: ProjectClass = item.pclass
        if pclass.use_project_tags:
            return True

    return False


def enrolled_for_pclasses_using_research_groups(fd: FacultyData):
    for item in fd.enrollments:
        item: EnrollmentRecord
        pclass: ProjectClass = item.pclass
        if pclass.advertise_research_group:
            return True

    return False


@faculty.route("/add_project", methods=["GET", "POST"])
@roles_required("faculty")
def add_project():
    fd: FacultyData = current_user.faculty_data

    uses_tags = enrolled_for_pclasses_using_tags(fd)
    uses_research_groups = enrolled_for_pclasses_using_research_groups(fd)

    # set up form
    AddProjectForm = AddProjectFormFactory(
        current_user.tenants.all(),
        convenor_editing=False,
        uses_tags=uses_tags,
        uses_research_groups=uses_research_groups,
    )
    form = AddProjectForm(request.form)

    if form.validate_on_submit():
        allowed_tenants = set([pcl.tenant_id for pcl in form.project_classes.data])
        tag_list = create_new_tags(form, allowed_tenants)

        data = Project(
            name=form.name.data,
            ATAS_restricted=form.ATAS_restricted.data,
            tags=tag_list if uses_tags else None,
            active=True,
            owner_id=current_user.faculty_data.id,
            generic=False,
            group=form.group.data if uses_research_groups else None,
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

        try:
            db.session.add(data)
            log_db_commit(
                f"Added new project '{data.name}' owned by {current_user.name}",
                user=current_user,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add new project due to a database error. Please contact a system administrator",
                "error",
            )

        if form.submit.data:
            return redirect(url_for("faculty.edit_descriptions", id=data.id, create=1))
        elif form.save_and_exit.data:
            return redirect(url_for("faculty.edit_projects"))
        elif form.save_and_preview:
            return redirect(
                url_for(
                    "faculty.project_preview",
                    id=data.id,
                    text="project list",
                    url=url_for("faculty.edit_projects"),
                )
            )
        else:
            raise RuntimeError("Unknown submit button in faculty.add_project")

    else:
        if request.method == "GET":
            owner = current_user.faculty_data

            if owner.show_popularity:
                form.show_popularity.data = True
                form.show_bookmarks.data = True
                form.show_selections.data = True
            else:
                form.show_popularity.data = False
                form.show_bookmarks.data = False
                form.show_selections.data = False

            form.enforce_capacity.data = owner.enforce_capacity
            form.dont_clash_presentations.data = owner.dont_clash_presentations

    return render_template_context(
        "faculty/edit_project.html",
        project_form=form,
        title="Add new project",
        submit_url=url_for("faculty.add_project"),
    )


@faculty.route("/edit_project/<int:id>", methods=["GET", "POST"])
@roles_required("faculty")
def edit_project(id):
    fd: FacultyData = current_user.faculty_data

    uses_tags = enrolled_for_pclasses_using_tags(fd)
    uses_research_groups = enrolled_for_pclasses_using_research_groups(fd)

    # set up form
    project: Project = Project.query.get_or_404(id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(project):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)
    if url is None:
        url = url_for("faculty.edit_projects")
        text = "project library"

    allowed_tenants = [pcl.tenant_id for pcl in project.project_classes]
    if len(allowed_tenants) == 0:
        allowed_tenants = current_user.tenants.all()
    EditProjectForm = EditProjectFormFactory(
        allowed_tenants,
        convenor_editing=False,
        uses_tags=uses_tags,
        uses_research_groups=uses_research_groups,
    )
    form = EditProjectForm(obj=project)
    form.project = project

    if form.validate_on_submit():
        allowed_tenants = set([pcl.tenant_id for pcl in form.project_classes.data])
        tag_list = create_new_tags(form, allowed_tenants)

        project.name = form.name.data
        project.ATAS_restricted = form.ATAS_restricted.data
        project.tags = tag_list if uses_tags else None
        project.group = form.group.data if uses_research_groups else None
        project.project_classes = form.project_classes.data
        project.meeting_reqd = form.meeting_reqd.data
        project.enforce_capacity = form.enforce_capacity.data
        project.show_popularity = form.show_popularity.data
        project.show_bookmarks = form.show_bookmarks.data
        project.show_selections = form.show_selections.data
        project.dont_clash_presentations = form.dont_clash_presentations.data
        project.last_edit_id = current_user.id
        project.last_edit_timestamp = datetime.now()

        # check that the specified programmes
        project.validate_programmes()

        try:
            log_db_commit(
                f"Edited project settings for '{project.name}' owned by {current_user.name}",
                user=current_user,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes due to a database error. Please contact a system administrator",
                "error",
            )

        if form.save_and_preview.data:
            return redirect(
                url_for("faculty.project_preview", id=id, text=text, url=url)
            )
        else:
            return redirect(url)

    return render_template_context(
        "faculty/edit_project.html",
        project_form=form,
        project=project,
        title="Edit project settings",
        url=url,
        text=text,
        submit_url=url_for("faculty.edit_project", id=project.id, url=url, text=text),
    )


@faculty.route("/remove_project_pclass/<int:proj_id>/<int:pclass_id>")
@roles_required("faculty")
def remove_project_pclass(proj_id, pclass_id):
    # get project details
    proj: Project = Project.query.get_or_404(proj_id)
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    try:
        proj.remove_project_class(pclass)
        log_db_commit(
            f"Removed project class '{pclass.name}' from project '{proj.name}'",
            user=current_user,
            project_classes=pclass,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not save changes due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@faculty.route("/activate_project/<int:id>")
@roles_required("faculty")
def activate_project(id):
    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    proj.enable()
    log_db_commit(
        f"Activated project '{proj.name}' owned by {current_user.name}",
        user=current_user,
    )

    return redirect(redirect_url())


@faculty.route("/deactivate_project/<int:id>")
@roles_required("faculty")
def deactivate_project(id):
    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(data):
        return redirect(redirect_url())

    data.disable()
    log_db_commit(
        f"Deactivated project '{data.name}' owned by {current_user.name}",
        user=current_user,
    )

    return redirect(redirect_url())


@faculty.route("/delete_project/<int:id>")
@roles_required("faculty")
def delete_project(id):
    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(data):
        return redirect(redirect_url())

    title = "Delete project"
    panel_title = "Delete project <strong>{name}</strong>".format(name=data.name)

    action_url = url_for("faculty.perform_delete_project", id=id, url=request.referrer)
    message = (
        "<p>Please confirm that you wish to delete the project "
        "<strong>{name}</strong>.</p>"
        "<p>This action cannot be undone.</p>".format(name=data.name)
    )
    submit_label = "Delete project"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@faculty.route("/perform_delete_project/<int:id>")
@roles_required("faculty")
def perform_delete_project(id):
    # get project details
    data = Project.query.get_or_404(id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("faculty.edit_projects")

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(data):
        return redirect(url)

    try:
        for item in data.descriptions:
            db.session.delete(item)

        db.session.delete(data)
        log_db_commit(
            f"Deleted project '{data.name}' owned by {current_user.name}",
            user=current_user,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not delete project due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(url)


@faculty.route("/add_description/<int:pid>", methods=["GET", "POST"])
@roles_required("faculty")
def add_description(pid):
    # get parent project details
    proj: Project = Project.query.get_or_404(pid)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
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
            confirmed=False,
            workflow_state=WorkflowMixin.WORKFLOW_APPROVAL_QUEUED,
            validator_id=None,
            validated_timestamp=None,
            capacity=form.capacity.data,
            review_only=form.review_only.data,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            db.session.add(data)
            log_db_commit(
                f"Added new description '{data.label}' for project '{proj.name}'",
                user=current_user,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not add new description due to a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url_for("faculty.edit_descriptions", id=pid, create=create))

    else:
        if request.method == "GET":
            form.capacity.data = proj.owner.project_capacity

    return render_template_context(
        "faculty/edit_description.html",
        project=proj,
        form=form,
        title="Add new description",
        create=create,
    )


@faculty.route("/edit_description/<int:did>", methods=["GET", "POST"])
@roles_required("faculty")
def edit_description(did):
    desc: ProjectDescription = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
        return redirect(redirect_url())

    create = request.args.get("create", default=None)
    focus_aims = bool(int(request.args.get("focus_aims", 0)))
    url = request.args.get("url", None)
    text = request.args.get("text", None)
    if url is None:
        url = url_for("faculty.edit_descriptions", id=desc.parent_id, create=create)
        text = "project variants list"

    EditDescriptionForm = EditDescriptionSettingsFormFactory(desc.parent_id, did)
    form = EditDescriptionForm(obj=desc)
    form.project_id = desc.parent_id
    form.desc = desc

    if focus_aims:
        if not hasattr(form.aims, "errors") or form.aims.errors is None:
            form.aims.errors = tuple()

        form.aims.errors = (
            *form.aims.errors,
            "Thank you for helping to improve our database. Please enter your statement of aims and save changes.",
        )

    if form.validate_on_submit():
        desc.label = form.label.data
        desc.project_classes = form.project_classes.data
        desc.aims = form.aims.data
        desc.team = form.team.data
        desc.capacity = form.capacity.data
        desc.review_only = form.review_only.data
        desc.last_edit_id = current_user.id
        desc.last_edit_timestamp = datetime.now()

        desc.validate_modules()

        try:
            log_db_commit(
                f"Edited description settings '{desc.label}' for project '{desc.parent.name}'",
                user=current_user,
            )
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
        title="Edit description",
        create=create,
        url=url,
        text=text,
    )


@faculty.route("/edit_description_content/<int:did>", methods=["GET", "POST"])
@roles_required("faculty")
def edit_description_content(did):
    desc: ProjectDescription = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
        return redirect(redirect_url())

    create = request.args.get("create", default=None)
    url = request.args.get("url", None)
    text = request.args.get("text", None)
    if url is None:
        url = url_for("faculty.edit_descriptions", id=desc.parent_id, create=create)
        text = "project variants list"

    form = EditDescriptionContentForm(obj=desc)

    if form.validate_on_submit():
        desc.description = form.description.data
        desc.reading = form.reading.data
        desc.last_edit_id = current_user.id
        desc.last_edit_timestamp = datetime.now()

        try:
            log_db_commit(
                f"Edited description content '{desc.label}' for project '{desc.parent.name}'",
                user=current_user,
            )
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
        title="Edit description",
        create=create,
        url=url,
        text=text,
    )


@faculty.route("/description_modules/<int:did>/<int:level_id>", methods=["GET", "POST"])
@faculty.route("/description_modules/<int:did>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def description_modules(did, level_id=None):
    desc = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
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
        "faculty/description_modules.html",
        project=desc.parent,
        desc=desc,
        form=form,
        title="Attach recommended modules",
        levels=levels,
        create=create,
        modules=modules,
        level_id=level_id,
    )


@faculty.route("/description_attach_module/<int:did>/<int:mod_id>/<int:level_id>")
@roles_accepted("faculty", "admin", "root")
def description_attach_module(did, mod_id, level_id):
    desc: ProjectDescription = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
        return redirect(redirect_url())

    create = request.args.get("create", default=None)
    module: Module = Module.query.get_or_404(mod_id)

    if desc.module_available(module.id):
        if module not in desc.modules:
            desc.modules.append(module)

            try:
                log_db_commit(
                    f"Attached recommended module '{module.name}' to description '{desc.label}' "
                    f"for project '{desc.parent.name}'",
                    user=current_user,
                )
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
            "faculty.description_modules", did=did, level_id=level_id, create=create
        )
    )


@faculty.route("/description_detach_module/<int:did>/<int:mod_id>/<int:level_id>")
@roles_accepted("faculty", "admin", "root")
def description_detach_module(did, mod_id, level_id):
    desc: ProjectDescription = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
        return redirect(redirect_url())

    create = request.args.get("create", default=None)
    module: Module = Module.query.get_or_404(mod_id)

    if module in desc.modules:
        desc.modules.remove(module)

        try:
            log_db_commit(
                f"Detached recommended module '{module.name}' from description '{desc.label}' "
                f"for project '{desc.parent.name}'",
                user=current_user,
            )
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
            "faculty.description_modules", did=did, level_id=level_id, create=create
        )
    )


@faculty.route("/delete_description/<int:did>")
@roles_required("faculty")
def delete_description(did):
    desc = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
        return redirect(redirect_url())

    try:
        db.session.delete(desc)
        log_db_commit(
            f"Deleted description '{desc.label}' from project '{desc.parent.name}'",
            user=current_user,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not delete project description due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@faculty.route("/duplicate_description/<int:did>")
@roles_required("faculty")
def duplicate_description(did):
    desc = ProjectDescription.query.get_or_404(did)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
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
        log_db_commit(
            f"Duplicated description '{desc.label}' as '{new_label}' for project '{desc.parent.name}'",
            user=current_user,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not duplicate project description due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@faculty.route("/move_description/<int:did>", methods=["GET", "POST"])
@roles_required("faculty")
def move_description(did):
    desc = ProjectDescription.query.get_or_404(did)
    old_project = desc.parent

    # if project owner is not logged-in user, object
    if not validate_edit_description(desc):
        return redirect(redirect_url())

    create = request.args.get("create", default=None)

    MoveDescriptionForm = MoveDescriptionFormFactory(
        old_project.owner_id, old_project.id
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
                log_db_commit(
                    f"Moved description '{desc.label}' from project '{old_project.name}' "
                    f"to project '{new_project.name}'",
                    user=current_user,
                )
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
                url_for("faculty.edit_descriptions", id=old_project.id, create=True)
            )
        else:
            return redirect(url_for("faculty.edit_descriptions", id=new_project.id))

    return render_template_context(
        "faculty/move_description.html",
        form=form,
        desc=desc,
        create=create,
        title='Move "{name}" to a new project'.format(name=desc.label),
    )


@faculty.route("/make_default_description/<int:pid>/<int:did>")
@faculty.route("/make_default_description/<int:pid>")
@roles_required("faculty")
def make_default_description(pid, did=None):
    proj = Project.query.get_or_404(pid)

    # if project owner is not logged-in user, object
    if not validate_edit_project(proj):
        return redirect(redirect_url())

    if did is not None:
        desc = ProjectDescription.query.get_or_404(did)

        if desc.parent_id != pid:
            flash(
                "Cannot set default description (id={did)) for project (id={pid}) because this description "
                "does not belong to the project".format(pid=pid, did=did),
                "error",
            )
            return redirect(redirect_url())

    proj.default_id = did
    log_db_commit(
        f"{'Set' if did is not None else 'Cleared'} default description for project '{proj.name}'",
        user=current_user,
    )

    return redirect(redirect_url())


@faculty.route("/attach_skills/<int:id>/<int:sel_id>")
@faculty.route("/attach_skills/<int:id>", methods=["GET", "POST"])
@roles_required("faculty")
def attach_skills(id, sel_id=None):
    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    form = SkillSelectorForm(request.form)

    # retain memory of which skill group is selected
    # (otherwise the form annoyingly resets itself everytime the page reloads)
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
        "faculty/attach_skills.html",
        data=proj,
        skills=skills,
        form=form,
        sel_id=form.selector.data.id,
        create=create,
    )


@faculty.route("/add_skill/<int:projectid>/<int:skillid>/<int:sel_id>")
@roles_required("faculty")
def add_skill(projectid, skillid, sel_id):
    # get project details
    proj = Project.query.get_or_404(projectid)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    create = request.args.get("create", default=None)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill not in proj.skills:
        proj.add_skill(skill)
        log_db_commit(
            f"Attached transferable skill '{skill.name}' to project '{proj.name}'",
            user=current_user,
        )

    return redirect(
        url_for("faculty.attach_skills", id=projectid, sel_id=sel_id, create=create)
    )


@faculty.route("/remove_skill/<int:projectid>/<int:skillid>/<int:sel_id>")
@roles_required("faculty")
def remove_skill(projectid, skillid, sel_id):
    # get project details
    proj = Project.query.get_or_404(projectid)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    create = request.args.get("create", default=None)

    skill = TransferableSkill.query.get_or_404(skillid)

    if skill in proj.skills:
        proj.remove_skill(skill)
        log_db_commit(
            f"Detached transferable skill '{skill.name}' from project '{proj.name}'",
            user=current_user,
        )

    return redirect(
        url_for("faculty.attach_skills", id=projectid, sel_id=sel_id, create=create)
    )


@faculty.route("/attach_programmes/<int:id>")
@roles_required("faculty")
def attach_programmes(id):
    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    q = proj.available_degree_programmes

    create = request.args.get("create", default=None)

    return render_template_context(
        "faculty/attach_programmes.html", data=proj, programmes=q.all(), create=create
    )


@faculty.route("/add_programme/<int:id>/<int:prog_id>")
@roles_required("faculty")
def add_programme(id, prog_id):
    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    programme = DegreeProgramme.query.get_or_404(prog_id)

    if proj.programmes is not None and programme not in proj.programmes:
        proj.add_programme(programme)
        log_db_commit(
            f"Attached degree programme '{programme.full_name}' to project '{proj.name}'",
            user=current_user,
        )

    return redirect(redirect_url())


@faculty.route("/remove_programme/<int:id>/<int:prog_id>")
@roles_required("faculty")
def remove_programme(id, prog_id):
    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    programme = DegreeProgramme.query.get_or_404(prog_id)

    if proj.programmes is not None and programme in proj.programmes:
        proj.remove_programme(programme)
        log_db_commit(
            f"Detached degree programme '{programme.full_name}' from project '{proj.name}'",
            user=current_user,
        )

    return redirect(redirect_url())


@faculty.route("/attach_assessors/<int:id>")
@roles_required("faculty")
def attach_assessors(id):
    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    create = request.args.get("create", default=None)

    state_filter = request.args.get("state_filter")
    pclass_filter = request.args.get("pclass_filter")
    group_filter = request.args.get("group_filter")

    # if no state filter supplied, check if one is stored in session
    if state_filter is None and session.get("faculty_marker_state_filter"):
        state_filter = session["faculty_marker_state_filter"]

    # write state filter into session if it is not empty
    if state_filter is not None:
        session["faculty_marker_state_filter"] = state_filter

    # if no pclass filter supplied, check if one is stored in session
    if pclass_filter is None and session.get("faculty_marker_pclass_filter"):
        pclass_filter = session["faculty_marker_pclass_filter"]

    # write pclass filter into session if it is not empty
    if pclass_filter is not None:
        session["faculty_marker_pclass_filter"] = pclass_filter

    # if no group filter supplied, check if one is stored in session
    if group_filter is None and session.get("faculty_marker_group_filter"):
        group_filter = session["faculty_marker_group_filter"]

    # write group filter into session if it is not empty
    if group_filter is not None:
        session["faculty_marker_group_filter"] = group_filter

    # get list of available research groups
    groups = ResearchGroup.query.filter_by(active=True).all()

    # get list of project classes to which this project is attached, and which require assignment of
    # second markers
    pclasses = proj.project_classes.filter(
        and_(
            ProjectClass.active.is_(True),
            or_(
                ProjectClass.uses_marker.is_(True),
                ProjectClass.uses_presentations.is_(True),
            ),
        )
    ).all()

    return render_template_context(
        "faculty/attach_assessors.html",
        data=proj,
        groups=groups,
        pclasses=pclasses,
        state_filter=state_filter,
        pclass_filter=pclass_filter,
        group_filter=group_filter,
        create=create,
    )


@faculty.route("/attach_assessors_ajax/<int:id>")
@roles_required("faculty")
def attach_assessors_ajax(id):
    # get project details
    proj = Project.query.get_or_404(id)

    # if project owner is not logged-in user, return empty json
    if not validate_is_project_owner(proj):
        return jsonify({})

    state_filter = request.args.get("state_filter")
    pclass_filter = request.args.get("pclass_filter")
    group_filter = request.args.get("group_filter")

    faculty = filter_assessors(proj, state_filter, pclass_filter, group_filter)

    return ajax.project.build_assessor_data(
        faculty,
        proj,
        _marker_menu,
        disable_enrollment_links=True,
        url=url_for("faculty.attach_assessors", id=id),
    )


@faculty.route("/add_assessor/<int:proj_id>/<int:mid>")
@roles_required("faculty")
def add_assessor(proj_id, mid):
    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    assessor = FacultyData.query.get_or_404(mid)

    proj.add_assessor(assessor, autocommit=True)

    return redirect(redirect_url())


@faculty.route("/remove_assessor/<int:proj_id>/<int:mid>")
@roles_required("faculty")
def remove_assessor(proj_id, mid):
    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    assessor = FacultyData.query.get_or_404(mid)

    proj.remove_assessor(assessor, autocommit=True)

    return redirect(redirect_url())


@faculty.route("/attach_all_assessors/<int:proj_id>")
@roles_required("faculty")
def attach_all_assessors(proj_id):
    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    state_filter = request.args.get("state_filter")
    pclass_filter = request.args.get("pclass_filter")
    group_filter = request.args.get("group_filter")

    assssors = filter_assessors(proj, state_filter, pclass_filter, group_filter)

    for assessor in assssors:
        proj.add_assessor(assessor, autocommit=False)

    log_db_commit(
        f"Attached all filtered assessors to project '{proj.name}'",
        user=current_user,
    )

    return redirect(redirect_url())


@faculty.route("/remove_all_assessors/<int:proj_id>")
@roles_required("faculty")
def remove_all_assessors(proj_id):
    # get project details
    proj = Project.query.get_or_404(proj_id)

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(proj):
        return redirect(redirect_url())

    state_filter = request.args.get("state_filter")
    pclass_filter = request.args.get("pclass_filter")
    group_filter = request.args.get("group_filter")

    assessors = filter_assessors(proj, state_filter, pclass_filter, group_filter)

    for assessor in assessors:
        proj.remove_assessor(assessor, autocommit=False)

    log_db_commit(
        f"Removed all filtered assessors from project '{proj.name}'",
        user=current_user,
    )

    return redirect(redirect_url())


@faculty.route("/preview/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root", "project_approver")
def project_preview(id):
    # get project details
    data = Project.query.get_or_404(id)

    # if project owner is not logged-in user or a suitable convenor, or an administrator, object
    if not validate_view_project(data):
        return redirect(redirect_url())

    show_selector = bool(int(request.args.get("show_selector", 1)))
    all_comments = bool(int(request.args.get("all_comments", 0)))
    all_workflow = bool(int(request.args.get("all_workflow", 0)))

    FacultyPreviewForm = FacultyPreviewFormFactory(id, show_selector)
    form = FacultyPreviewForm(request.form)

    current_year = get_current_year()

    pclass_id = request.args.get("pclass", None)

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    if hasattr(form, "selector"):
        if form.selector.data is None:
            # check whether pclass was passed in as an argument
            if pclass_id is None:
                # attach first available project class
                form.selector.data = data.project_classes.first()

            else:
                if pclass_id is not None:
                    pclass = data.project_classes.filter_by(id=pclass_id).first()
                    if pclass is not None:
                        form.selector.data = pclass
                    else:
                        form.selector.data = data.project_classes.first()
                else:
                    form.selector.data = None

        desc = data.get_description(form.selector.data)

    else:
        if pclass_id is not None:
            pclass = data.project_classes.filter_by(id=pclass_id).first()
            desc = data.get_description(pclass)
        else:
            desc = data.get_description(data.project_classes.first())

    if form.post_comment.data and form.validate():
        vis = DescriptionComment.VISIBILITY_EVERYONE
        if current_user.has_role("project_approver"):
            if form.limit_visibility.data:
                vis = DescriptionComment.VISIBILITY_APPROVALS_TEAM

        comment = DescriptionComment(
            year=current_year,
            owner_id=current_user.id,
            parent_id=desc.id,
            comment=form.comment.data,
            visibility=vis,
            deleted=False,
            creation_timestamp=datetime.now(),
        )
        db.session.add(comment)
        log_db_commit(
            f"Posted comment on description '{desc.label}' for project '{data.name}'",
            user=current_user,
        )

        # notify watchers on this thread that a new comment has been posted
        celery = current_app.extensions["celery"]
        notify = celery.tasks["app.tasks.issue_confirm.notify_comment"]
        notify.apply_async(args=(comment.id,))

        form.comment.data = None

    # defaults for comments pane
    form.limit_visibility.data = (
        True if current_user.has_role("project_approver") else False
    )

    allow_approval = (
        (current_user.has_role("project_approver") or current_user.has_role("root"))
        and desc is not None
        and allow_approval_for_description(desc.id)
    )

    show_comments = (
        allow_approval
        or (data.owner is not None and current_user.id == data.owner.id)
        or current_user.has_role("convenor")
    )

    if desc is not None:
        if all_workflow:
            workflow_history = desc.workflow_history.order_by(
                ProjectDescriptionWorkflowHistory.timestamp.asc()
            ).all()
        else:
            workflow_history = (
                desc.workflow_history.filter_by(year=current_year)
                .order_by(ProjectDescriptionWorkflowHistory.timestamp.asc())
                .all()
            )

        if all_comments:
            comments = desc.comments.order_by(
                DescriptionComment.creation_timestamp.asc()
            ).all()
        else:
            comments = (
                desc.comments.filter_by(year=current_year)
                .order_by(DescriptionComment.creation_timestamp.asc())
                .all()
            )
    else:
        workflow_history = []
        comments = []

    data.update_last_viewed_time(current_user, commit=True)

    return render_project(
        data,
        desc,
        form=form,
        text=text,
        url=url,
        show_selector=show_selector,
        allow_approval=allow_approval,
        show_comments=show_comments,
        comments=comments,
        all_comments=all_comments,
        all_workflow=all_workflow,
        pclass_id=pclass_id,
        workflow_history=workflow_history,
    )


@faculty.route("/dashboard")
@roles_required("faculty")
def dashboard():
    """
    Render the dashboard for a faculty user
    :return:
    """
    # check for unofferable projects and warn if any are present
    fd: FacultyData = current_user.faculty_data

    main_config: MainConfig = get_main_config()
    if main_config.enable_2026_ATAS_campaign:
        # only consider jumping to landing page if this user belongs to a tenant participating in the campaign
        if (
            get_count(
                current_user.tenants.filter(Tenant.in_2026_ATAS_campaign.is_(True))
            )
            > 0
        ):
            data = check_2026_ATAS(fd)
            if len(data["projects"]) > 0:
                return redirect(url_for("campaigns.atas_2026"))

    num_unofferable = fd.projects_unofferable
    if num_unofferable > 0:
        plural = "" if num_unofferable == 1 else "s"
        isare = "is" if num_unofferable == 1 else "are"
        itthey = "it has" if num_unofferable == 1 else "they have"

        flash(
            f"You have {num_unofferable} project{plural} that {isare} active but cannot be offered to students because {itthey} validation errors. Please check your project list.",
            "error",
        )

    # build list of current configuration records for all enrolled project classes
    enrolments = []
    enrolment_panes = []
    enrolment_labels = {}

    for record in fd.ordered_enrollments:
        pclass: ProjectClass = record.pclass
        config: ProjectClassConfig = pclass.most_recent_config

        if pclass.active and pclass.publish and config is not None:
            include = False

            if (
                (
                    pclass.uses_supervisor
                    and record.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED
                )
                or (
                    config.uses_marker
                    and config.display_marker
                    and record.marker_state == EnrollmentRecord.MARKER_ENROLLED
                )
                or (
                    config.uses_presentations
                    and config.display_presentations
                    and record.presentations_state
                    == EnrollmentRecord.PRESENTATIONS_ENROLLED
                )
            ):
                include = True

            else:
                for n in range(config.number_submissions):
                    period: SubmissionPeriodRecord = config.get_period(n + 1)

                    num_s_records = period.number_supervisor_records(current_user.id)
                    num_mk_records = period.number_marker_records(current_user.id)
                    num_mo_records = period.number_moderator_records(current_user.id)
                    num_p_records = period.number_presentation_records(current_user.id)

                    if (
                        (pclass.uses_supervisor and num_s_records > 0)
                        or (
                            config.uses_marker
                            and config.display_marker
                            and num_mk_records > 0
                        )
                        or (
                            config.uses_moderator
                            and config.display_marker
                            and num_mo_records > 0
                        )
                        or (
                            config.uses_presentations
                            and config.display_presentations
                            and num_p_records > 0
                        )
                    ):
                        include = True
                        break

            if include:
                # get live projects belonging to both this config item and the active user
                live_projects = config.live_projects.filter_by(owner_id=current_user.id)

                enrolments.append(
                    {"config": config, "projects": live_projects, "record": record}
                )
                enrolment_panes.append(str(config.id))
                enrolment_labels[str(config.id)] = config.name

    # build list of system messages to consider displaying
    messages = []
    for message in (
        db.session.query(MessageOfTheDay)
        .filter(
            MessageOfTheDay.show_faculty,
            ~MessageOfTheDay.dismissed_by.any(id=current_user.id),
        )
        .order_by(MessageOfTheDay.issue_date.desc())
        .all()
    ):
        include = message.project_classes.first() is None
        if not include:
            for pcl in message.project_classes:
                if fd.is_enrolled(pcl):
                    include = True
                    break

        if include:
            messages.append(message)

    # Find MarkingReports requiring sign-off by this user (ROLE_RESPONSIBLE_SUPERVISOR)
    from ..models.markingevent import marking_report_to_responsible_supervisors

    pending_sign_off_reports = (
        db.session.query(MarkingReport)
        .join(
            marking_report_to_responsible_supervisors,
            marking_report_to_responsible_supervisors.c.marking_report_id == MarkingReport.id,
        )
        .filter(
            marking_report_to_responsible_supervisors.c.submission_role_id.in_(
                db.session.query(SubmissionRole.id).filter(SubmissionRole.user_id == current_user.id)
            ),
            MarkingReport.signed_off_id.is_(None),
        )
        .all()
    )

    # Find pending moderator reports for this user
    pending_moderator_reports = (
        db.session.query(ModeratorReport)
        .join(SubmissionRole, SubmissionRole.id == ModeratorReport.role_id)
        .filter(
            SubmissionRole.user_id == current_user.id,
            ModeratorReport.report_submitted.is_(False),
        )
        .all()
    )

    # Compute unique workflow attachments visible to ROLE_MODERATOR, for the moderator dashboard pane
    seen_workflow_ids: set = set()
    moderator_workflow_attachments: List[Dict] = []
    for mod_report in pending_moderator_reports:
        sr = mod_report.submitter_report
        if sr is not None:
            workflow = sr.workflow
            if workflow is not None and workflow.id not in seen_workflow_ids:
                seen_workflow_ids.add(workflow.id)
                files = [pa for pa in workflow.attachments if pa.has_role_access(SubmissionRoleTypesMixin.ROLE_MODERATOR)]
                if files:
                    moderator_workflow_attachments.append({"workflow": workflow, "attachments": files})

    # Find pending marking reports for this user (distributed but not yet closed)
    from sqlalchemy import and_

    pending_marking_reports = (
        db.session.query(MarkingReport)
        .join(SubmissionRole, SubmissionRole.id == MarkingReport.role_id)
        .filter(
            SubmissionRole.user_id == current_user.id,
            MarkingReport.distributed.is_(True),
            or_(
                MarkingReport.report_submitted.isnot(True),
                MarkingReport.feedback_submitted.isnot(True),
            ),
        )
        .all()
    )
    # Filter in Python for the time-based window (marking_form_is_open)
    pending_marking_reports = [
        r for r in pending_marking_reports if r.marking_form_is_open
    ]

    pane = request.args.get("pane", None)
    if pane is None and session.get("faculty_dashboard_pane"):
        pane = session["faculty_dashboard_pane"]

    if pane is None:
        if current_user.has_role("root"):
            pane = "system"
        elif pending_sign_off_reports:
            pane = "signoff"
        elif pending_moderator_reports:
            pane = "moderation"
        elif pending_marking_reports:
            pane = "marking"
        elif len(enrolments) > 0:
            pane = "enrolments"

    num_enrolment_panes = len(enrolment_panes)
    if pane == "system":
        if not current_user.has_role("root"):
            if num_enrolment_panes > 0:
                pane = enrolment_panes[0]
            else:
                pane = None

    elif pane == "approve":
        if not (
            current_user.has_role("user_approver")
            or current_user.has_role("project_approver")
            or current_user.has_role("admin")
            or current_user.has_role("root")
        ):
            if num_enrolment_panes > 0:
                pane = enrolment_panes[0]
            else:
                pane = None

    elif pane == "marking":
        pass  # always valid if pending_marking_reports is non-empty

    elif pane == "signoff":
        pass  # always valid if pending_sign_off_reports is non-empty

    elif pane == "moderation":
        pass  # always valid if pending_moderator_reports is non-empty

    else:
        if pane != "enrolments" and pane not in enrolment_panes:
            if num_enrolment_panes > 0:
                pane = "enrolments"
            else:
                pane = None

        # mark any unviewed confirmation requests as viewed, but do it with a 15 sec delay so that the
        # NEW labels don't disappear immediately
        if pane is not None and pane not in ["system", "approve", "marking", "enrolments"]:
            celery = current_app.extensions["celery"]
            remove_new = celery.tasks["app.tasks.selecting.remove_new"]
            remove_new.apply_async(args=(int(pane), current_user.id), countdown=15)

    if pane is not None:
        session["faculty_dashboard_pane"] = pane

    if current_user.has_role("root"):
        root_dash_data = get_root_dashboard_data()
    else:
        root_dash_data = None

    approvals_data = get_approval_queue_data()
    num_enrolments = len(enrolments)

    return render_template_context(
        "faculty/dashboard/dashboard.html",
        enrolments=enrolments,
        num_enrolments=num_enrolments,
        messages=messages,
        root_dash_data=root_dash_data,
        approvals_data=approvals_data,
        pane=pane,
        pane_label=enrolment_labels.get(pane, None),
        pane_is_system=pane == "system",
        pane_is_approve=pane == "approve",
        pane_is_marking=pane == "marking",
        pane_is_signoff=pane == "signoff",
        pane_is_moderation=pane == "moderation",
        pane_is_enrollment=pane == "enrolments" or pane in enrolment_panes,
        is_user_approver=current_user.has_role("user_approver"),
        is_project_approver=current_user.has_role("project_approver"),
        today=date.today(),
        pending_marking_reports=pending_marking_reports,
        pending_sign_off_reports=pending_sign_off_reports,
        pending_moderator_reports=pending_moderator_reports,
        moderator_workflow_attachments=moderator_workflow_attachments,
    )


@faculty.route("/confirm_pclass/<int:id>")
@roles_required("faculty")
def confirm_pclass(id):
    """
    Issue confirmation for this project class and logged-in user
    :param id:
    :return:
    """
    # get current configuration record for this project class
    pclass: ProjectClass = db.session.query(ProjectClass).filter_by(id=id).first()
    config: ProjectClassConfig = pclass.most_recent_config

    if not config.requests_issued:
        flash(
            "Confirmation requests have not yet been issued for {project} "
            "{yeara}-{yearb}".format(
                project=config.name,
                yeara=config.submit_year_a,
                yearb=config.submit_year_b,
            )
        )
        return redirect(redirect_url())

    if config.live:
        flash(
            "Confirmation is no longer required for {project} {yeara}-{yearb} because this project "
            "has already gone live".format(
                project=config.name,
                yeara=config.submit_year_a,
                yearb=config.submit_year_b,
            )
        )
        return redirect(redirect_url())

    if not config.is_confirmation_required(current_user.faculty_data):
        flash(
            "You have no outstanding confirmation requests for {project} {yeara}-{yearb}".format(
                project=config.name,
                yeara=config.submit_year_a,
                yearb=config.submit_year_b,
            )
        )
        return redirect(redirect_url())

    messages = []
    try:
        messages = config.mark_confirmed(current_user.faculty_data, message=True)
        log_db_commit(
            f"Faculty member {current_user.name} confirmed all projects for class '{config.name}'",
            user=current_user,
            project_classes=pclass,
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            'Could not projects for class "{pclass}" due to a database error. '
            "Please contact a system administrator".format(pclass=config.name),
            "error",
        )

    else:
        for msg, level in messages:
            flash(msg, level)

    # kick off a background task to check whether any other project classes in which this user is enrolled
    # have been reduced to zero confirmations left.
    # If so, treat this 'Confirm' click as accounting for them also
    celery = current_app.extensions["celery"]
    task = celery.tasks["app.tasks.issue_confirm.propagate_confirm"]
    task.apply_async(args=(current_user.id, id))

    return redirect(redirect_url())


@faculty.route("/confirm_description/<int:did>/<int:pclass_id>")
@roles_required("faculty")
def confirm_description(did, pclass_id):
    desc: ProjectDescription = ProjectDescription.query.get_or_404(did)

    # get current configuration record for this project class
    pcl: ProjectClass = db.session.query(ProjectClass).filter_by(id=pclass_id).first()
    config: ProjectClassConfig = pcl.most_recent_config

    if not config.requests_issued:
        flash(
            "Confirmation requests have not yet been issued for {project} {yeara}-{yearb}".format(
                project=config.name,
                yeara=config.submit_year_a,
                yearb=config.submit_year_b,
            )
        )
        return redirect(redirect_url())

    if config.live:
        flash(
            "Confirmation is no longer required for {project} {yeara}-{yearb} because this project "
            "has already gone live".format(
                project=config.name,
                yeara=config.submit_year_a,
                yearb=config.submit_year_b,
            )
        )
        return redirect(redirect_url())

    # if project owner is not logged-in user, object
    if not validate_is_project_owner(desc.parent):
        return redirect(redirect_url())

    messages = []
    try:
        desc.confirmed = True
        db.session.flush()

        # if no further confirmations outstanding, mark whole configuration as confirmed
        if not config.has_confirmations_outstanding(current_user.faculty_data):
            messages = config.mark_confirmed(current_user.faculty_data, message=True)

        log_db_commit(
            f"Faculty member {current_user.name} confirmed description '{desc.label}' "
            f"for project '{desc.parent.name}' in class '{pcl.name}'",
            user=current_user,
            project_classes=pcl,
        )

        # kick off a background task to check whether any other project classes in which this user is enrolled
        # have been reduced to zero confirmations left.
        # If so, treat this 'Confirm' click as accounting for them also
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.issue_confirm.propagate_confirm"]
        task.apply_async(args=(current_user.id, pclass_id))

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            'Could not confirm description "{desc}" for project "{proj}" due to a database error. '
            "Please contact a system administrator".format(
                desc=desc.label, proj=desc.parent.name
            ),
            "error",
        )

    else:
        for msg, level in messages:
            flash(msg, level)

    return redirect(redirect_url())


@faculty.route("/confirm/<int:sid>/<int:pid>")
@roles_required("faculty")
def confirm(sid, pid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify that logged-in user is the owner of this liveproject
    if not validate_is_project_owner(project):
        return redirect(redirect_url())

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(url_for(request.referrer))

    if do_confirm(sel, project, resolved_by=current_user):
        log_db_commit(
            f"Confirmed selection of project '{project.name}' for student {sel.student.user.name}",
            user=current_user,
            project_classes=project.config.project_class,
        )

    return redirect(redirect_url())


@faculty.route("/deconfirm_to_pending/<int:sid>/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def deconfirm_to_pending(sid, pid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify that logged-in user is the owner of this liveproject
    if not validate_is_project_owner(project):
        return redirect(redirect_url())

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(url_for(request.referrer))

    if do_deconfirm_to_pending(sel, project):
        log_db_commit(
            f"Moved selection of project '{project.name}' by student {sel.student.user.name} back to pending",
            user=current_user,
            project_classes=project.config.project_class,
        )

    return redirect(redirect_url())


@faculty.route("/cancel_confirm/<int:sid>/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def cancel_confirm(sid, pid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    # verify that logged-in user is the owner of this liveproject
    if not validate_is_project_owner(project):
        return redirect(redirect_url())

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(url_for(request.referrer))

    if do_cancel_confirm(sel, project):
        log_db_commit(
            f"Cancelled confirmation of project '{project.name}' for student {sel.student.user.name}",
            user=current_user,
            project_classes=project.config.project_class,
        )

    return redirect(redirect_url())


@faculty.route("/live_project/<int:pid>")
@roles_accepted("student", "faculty", "admin", "root")
def live_project(pid):
    """
    View a specific project on the live system
    :param tabid:
    :param classid:
    :param pid:
    :return:
    """

    # pid is the id for a LiveProject
    data = LiveProject.query.get_or_404(pid)

    text = request.args.get("text", None)
    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    return render_project(data, data, text=text, url=url)


@faculty.route("/past_projects")
@roles_required("faculty")
def past_projects():
    """
    Show list of previously offered projects, extracted from live table
    :return:
    """

    return render_template_context("faculty/past_projects.html")


@faculty.route("/past_projects_ajax")
@roles_required("faculty")
def past_projects_ajax():
    """
    Ajax data point for list of previously offered projects
    :return:
    """

    past_projects = LiveProject.query.filter_by(owner_id=current_user.id)

    return ajax.faculty.pastproject_data(past_projects)


@faculty.route("/edit_feedback/<int:id>", methods=["GET", "POST"])
@roles_required("faculty")
def edit_feedback(id):
    # id is a SubmissionRole instance
    role: SubmissionRole = SubmissionRole.query.get_or_404(id)
    record: SubmissionRecord = role.submission

    if record.retired:
        flash(
            "It is not possible to edit feedback for submissions that have been retired.",
            "error",
        )
        return redirect(redirect_url())

    if not validate_submission_role(
        role, allow_roles=["supervisor", "marker", "moderator"]
    ):
        return redirect(redirect_url())

    period: SubmissionPeriodRecord = record.period

    if not period.is_feedback_open:
        flash(
            "It is not yet possible to edit feedback for this submission because the convenor has not "
            "opened this submission period for feedback and marking.",
            "warning",
        )
        return redirect(redirect_url())

    if period.closed and role.submitted_feedback:
        flash(
            "It is not possible to edit feedback after the convenor has closed this submission period.",
            "warning",
        )
        return redirect(redirect_url())

    form = SubmissionRoleFeedbackForm(request.form)

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    if form.validate_on_submit():
        role.positive_feedback = form.positive_feedback.data
        role.improvements_feedback = form.improvement_feedback.data

        if role.submitted_feedback:
            role.feedback_timestamp = datetime.now()

        try:
            log_db_commit(
                f"Saved feedback for submission by {record.student_identifier['label']} "
                f"(role: {role.role_label})",
                user=current_user,
                project_classes=period.config.project_class,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save feedback due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url)

    else:
        if request.method == "GET":
            form.positive_feedback.data = role.positive_feedback
            form.improvement_feedback.data = role.improvements_feedback

    return render_template_context(
        "faculty/dashboard/edit_feedback.html",
        form=form,
        title="Edit feedback",
        unique_id="role-{id}".format(id=role.id),
        formtitle='Edit feedback for <i class="fas fa-user-circle"></i> '
        "<strong>{name}</strong>".format(name=record.student_identifier["label"]),
        submit_url=url_for("faculty.edit_feedback", id=id, url=url),
        period=period,
        record=role,
    )


@faculty.route("/submit_feedback/<int:id>")
@roles_required("faculty")
def submit_feedback(id):
    # id is a SubmissionRole instance
    role: SubmissionRole = SubmissionRole.query.get_or_404(id)
    record: SubmissionRecord = role.submission

    if record.retired:
        flash(
            "It is not possible to submit feedback for submissions that have been retired.",
            "error",
        )
        return redirect(redirect_url())

    if not validate_submission_role(
        role, allow_roles=["supervisor", "marker", "moderator"]
    ):
        return redirect(redirect_url())

    record: SubmissionRecord = role.submission
    period: SubmissionPeriodRecord = record.period

    if not period.is_feedback_open:
        flash(
            "It is not yet possible to submit feedback for this submission because the convenor has not "
            "opened this submission period for feedback and marking.",
            "warning",
        )
        return redirect(redirect_url())

    if period.closed and role.submitted_feedback:
        flash(
            "It is not possible to submit feedback after the convenor has closed this submission period.",
            "warning",
        )
        return redirect(redirect_url())

    if not role.feedback_valid:
        flash(
            "It is not yet possible to submit your feedback because it is incomplete. Please ensure that you "
            "have provided responses for each category.",
            "warning",
        )
        return redirect(redirect_url())

    if role.submitted_feedback:
        return redirect(redirect_url())

    try:
        role.submitted_feedback = True
        role.feedback_timestamp = datetime.now()

        log_db_commit(
            f"Submitted feedback for submission by {record.student_identifier['label']} "
            f"(role: {role.role_label})",
            user=current_user,
            project_classes=period.config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not submit feedback due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(redirect_url())


@faculty.route("/unsubmit_feedback/<int:id>")
@roles_required("faculty")
def unsubmit_feedback(id):
    # id is a SubmissionRole instance
    role: SubmissionRole = SubmissionRole.query.get_or_404(id)
    record: SubmissionRecord = role.submission

    if record.retired:
        flash(
            "It is not possible to unsubmit feedback for submissions that have been retired.",
            "error",
        )
        return redirect(redirect_url())

    if not validate_submission_role(
        role, allow_roles=["supervisor", "marker", "moderator"]
    ):
        return redirect(redirect_url())

    record: SubmissionRecord = role.submission
    period: SubmissionPeriodRecord = record.period

    if not role.submitted_feedback:
        flash(
            "Your feedback has not yet been submitted, and cannot be unsubmitted.",
            "info",
        )
        return redirect(redirect_url())

    if period.closed and role.submitted_feedback:
        flash(
            "It is not possible to unsubmit after the feedback period has closed.",
            "warning",
        )
        return redirect(redirect_url())

    try:
        role.submitted_feedback = False
        role.feedback_timestamp = None

        log_db_commit(
            f"Unsubmitted feedback for submission by {record.student_identifier['label']} "
            f"(role: {role.role_label})",
            user=current_user,
            project_classes=period.config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not unsubmit feedback due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(redirect_url())


@faculty.route("/view_feedback/<int:id>")
@roles_required("faculty")
def view_feedback(id):
    # id is a SubmissionRecord instance
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(id)

    if not validate_submission_viewable(record):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)
    if url is None:
        url = redirect_url()

    preview = request.args.get("preview", None)

    return render_template_context(
        "faculty/dashboard/view_feedback.html",
        record=record,
        text=text,
        url=url,
        preview=preview,
    )


@faculty.route("/edit_response/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty")
def edit_response(id):
    # id identifies a SubmissionRole instance
    role: SubmissionRole = SubmissionRecord.query.get_or_404(id)
    record: SubmissionRecord = role.submission

    if record.retired:
        flash(
            "It is not possible to edit a response to the submitted for submissions that have been retired.",
            "error",
        )
        return redirect(redirect_url())

    if not validate_submission_role(role, allow_roles=["supervisor"]):
        return redirect(redirect_url())

    period: SubmissionPeriodRecord = record.period

    if not period.closed:
        flash(
            "It is only possible to respond to feedback from the submitter when "
            "their own marks and feedback are available. "
            "Try again when this submission period is closed.",
            "info",
        )
        return redirect(redirect_url())

    if period.closed and role.submitted_response:
        flash(
            "It is not possible to edit your response once it has been submitted",
            "info",
        )
        return redirect(redirect_url())

    form = SubmissionRoleResponseForm(request.form)

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    if form.validate_on_submit():
        role.response = form.feedback.data

        try:
            log_db_commit(
                f"Saved response to student feedback for submission by {record.student_identifier['label']}",
                user=current_user,
                project_classes=period.config.project_class,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save response due to a database error. Please contact a system administrator.",
                "error",
            )

        return redirect(url)

    else:
        if request.method == "GET":
            form.feedback.data = role.response

    return render_template_context(
        "faculty/dashboard/edit_response.html",
        form=form,
        record=role,
        submit_url=url_for("faculty.edit_response", id=id, url=url),
        url=url,
    )


@faculty.route("/submit_response/<int:id>")
@roles_accepted("faculty")
def submit_response(id):
    # id identifies a SubmissionRole instance
    role: SubmissionRole = SubmissionRole.query.get_or_404(id)
    record: SubmissionRecord = role.submission

    if record.retired:
        flash(
            "It is not possible to submit a response to the submitter for submissions that have been retired.",
            "error",
        )
        return redirect(redirect_url())

    if not validate_submission_role(role, allow_roles=["supervisor"]):
        return redirect(redirect_url())

    period: SubmissionPeriodRecord = record.period

    if role.submitted_response:
        return redirect(redirect_url())

    if not period.closed:
        flash(
            "It is only possible to respond to feedback from the submitter when "
            "their own marks and feedback are available. "
            "Try again when this submission period is closed.",
            "info",
        )
        return redirect(redirect_url())

    if not role.response_valid:
        flash(
            "Your response cannot be submitted because it is incomplete. Please ensure that you have provided responses for each category.",
            "info",
        )
        return redirect(redirect_url())

    try:
        role.submitted_response = True
        role.response_timestamp = datetime.now()

        log_db_commit(
            f"Submitted response to student feedback for submission by {record.student_identifier['label']}",
            user=current_user,
            project_classes=period.config.project_class,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not submit response due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(redirect_url())


@faculty.route("/set_availability/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty")
def set_availability(id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(id)

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability:
        flash(
            "Cannot set availability for this assessment because it has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    if assessment.availability_closed:
        flash(
            "Cannot set availability for this assessment because it has been closed",
            "info",
        )
        return redirect(redirect_url())

    include_confirm = assessment.is_faculty_outstanding(current_user.id)
    AvailabilityForm = AvailabilityFormFactory(include_confirm)
    form = AvailabilityForm(request.form)

    if form.validate_on_submit():
        comment = form.comment.data
        if len(comment) == 0:
            comment = None

        assessment.faculty_set_comment(current_user.faculty_data, comment)

        if hasattr(form, "confirm") and form.confirm:
            record = assessment.assessor_list.filter_by(
                faculty_id=current_user.id, confirmed=False
            ).first()
            if record is not None:
                record.confirmed = True
                record.confirmed_timestamp = datetime.now()

            flash(
                "Your availability details have been recorded. Thank you for responding.",
                "info",
            )

        elif hasattr(form, "update") and form.update:
            flash("Thank you: your availability details have been updated", "info")

        else:
            raise RuntimeError("Unknown submit button in faculty.set_availability")

        try:
            log_db_commit(
                f"Set availability for assessment '{assessment.name}' by {current_user.name}",
                user=current_user,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not save changes due to a database error. Please contact a system administrator",
                "error",
            )

        return home_dashboard()

    else:
        if request.method == "GET":
            form.comment.data = assessment.faculty_get_comment(
                current_user.faculty_data
            )

    return render_template_context(
        "faculty/set_availability.html",
        form=form,
        assessment=assessment,
        url=url,
        text=text,
    )


@faculty.route("/session_available/<int:sess_id>")
@roles_accepted("faculty")
def session_available(sess_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    session: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = session.owner

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot set availability for this assessment because availability collection has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    if assessment.availability_closed:
        flash(
            "Cannot set availability for this session because its parent assessment has been closed",
            "info",
        )
        return redirect(redirect_url())

    session.faculty_make_available(current_user.faculty_data)

    try:
        log_db_commit(
            f"Marked session '{session.short_date_string}' as available for assessment '{assessment.name}' "
            f"by {current_user.name}",
            user=current_user,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not save changes due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@faculty.route("/session_ifneeded/<int:sess_id>")
@roles_accepted("faculty")
def session_ifneeded(sess_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    session: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = session.owner

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot set availability for this session because availability collection for its parent assessment has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    if assessment.availability_closed:
        flash(
            "Cannot set availability for this session because its parent assessment has been closed",
            "info",
        )
        return redirect(redirect_url())

    session.faculty_make_ifneeded(current_user.faculty_data)

    try:
        log_db_commit(
            f"Marked session '{session.short_date_string}' as if-needed for assessment '{assessment.name}' "
            f"by {current_user.name}",
            user=current_user,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not save changes due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@faculty.route("/session_unavailable/<int:sess_id>")
@roles_accepted("faculty")
def session_unavailable(sess_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    session: PresentationSession = PresentationSession.query.get_or_404(sess_id)
    assessment: PresentationAssessment = session.owner

    current_year = get_current_year()
    if not validate_assessment(session.owner, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot set availability for this session because availability collection for its parent assessment has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    if assessment.availability_closed:
        flash(
            "Cannot set availability for this session because its parent assessment has been closed",
            "info",
        )
        return redirect(redirect_url())

    session.faculty_make_unavailable(current_user.faculty_data)

    try:
        log_db_commit(
            f"Marked session '{session.short_date_string}' as unavailable for assessment '{assessment.name}' "
            f"by {current_user.name}",
            user=current_user,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not save changes due to a database error. Please contact a system administrator",
            "error",
        )

    return redirect(redirect_url())


@faculty.route("/session_all_available/<int:sess_id>")
@roles_accepted("faculty")
def session_all_available(sess_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(
        sess_id
    )

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot set availability for this session because availability collection for its parent assessment has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    if assessment.availability_closed:
        flash(
            "Cannot set availability for this session because its parent assessment has been closed",
            "info",
        )
        return redirect(redirect_url())

    for session in assessment.sessions:
        session.faculty_make_available(current_user.faculty_data)

    log_db_commit(
        f"Marked all sessions as available for assessment '{assessment.name}' by {current_user.name}",
        user=current_user,
    )

    return redirect(redirect_url())


@faculty.route("/session_all_unavailable/<int:sess_id>")
@roles_accepted("faculty")
def session_all_unavailable(sess_id):
    if not validate_using_assessment():
        return redirect(redirect_url())

    assessment: PresentationAssessment = PresentationAssessment.query.get_or_404(
        sess_id
    )

    current_year = get_current_year()
    if not validate_assessment(assessment, current_year=current_year):
        return redirect(redirect_url())

    if not assessment.requested_availability and not assessment.skip_availability:
        flash(
            "Cannot set availability for this session because availability collection for its parent assessment has not yet been opened",
            "info",
        )
        return redirect(redirect_url())

    if assessment.availability_closed:
        flash(
            "Cannot set availability for this session because its parent assessment has been closed",
            "info",
        )
        return redirect(redirect_url())

    for session in assessment.sessions:
        session.faculty_make_unavailable(current_user.faculty_data)

    log_db_commit(
        f"Marked all sessions as unavailable for assessment '{assessment.name}' by {current_user.name}",
        user=current_user,
    )

    return redirect(redirect_url())


@faculty.route("/change_availability")
@roles_accepted("faculty")
def change_availability():
    if not validate_using_assessment():
        return redirect(redirect_url())

    return render_template_context("faculty/change_availability.html")


@faculty.route("/show_enrollments")
@roles_required("faculty")
def show_enrollments():
    data: FacultyData = FacultyData.query.get_or_404(current_user.id)

    user_tenant_ids: List[int] = [t.id for t in current_user.tenants]

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

        # avoid circular references
        if url is not None and "show_enrollments" in url:
            url = None

    pclasses: List[ProjectClass] = (
        db.session.query(ProjectClass)
        .filter(
            and_(
                ProjectClass.active.is_(True),
                ProjectClass.publish.is_(True),
                ProjectClass.tenant_id.in_(user_tenant_ids),
            ),
        )
        .order_by(ProjectClass.name)
        .all()
    )
    pclasses_binned = [(p, data.is_enrolled(p)) for p in pclasses]
    enrolled_pclasses = [
        data.get_enrollment_record(p) for p, flag in pclasses_binned if flag
    ]
    unenrolled_pclasses = [p for p, flag in pclasses_binned if not flag]

    return render_template_context(
        "faculty/show_enrollments.html",
        data=data,
        url=url,
        enrolment_records=enrolled_pclasses,
        unenrolled_pclasses=unenrolled_pclasses,
    )


@faculty.route("/show_workload")
@roles_required("faculty")
def show_workload():
    data = FacultyData.query.get_or_404(current_user.id)

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

        # avoid circular references
        if isinstance(url, str) and "show_workload" in url:
            url = None

    return render_template_context("faculty/show_workload.html", data=data, url=url)


@faculty.route("/settings", methods=["GET", "POST"])
@roles_required("faculty")
def settings():
    """
    Edit settings for a faculty member
    :return:
    """
    user: User = User.query.get_or_404(current_user.id)
    fd: FacultyData = FacultyData.query.get_or_404(current_user.id)

    main_config = get_main_config()

    FacultySettingsForm = FacultySettingsFormFactory(
        user,
        current_user,
        enable_canvas=main_config.enable_canvas_sync and fd.is_convenor,
    )
    form = FacultySettingsForm(obj=fd)
    form.user = user

    if form.validate_on_submit():
        user.first_name = form.first_name.data
        user.last_name = form.last_name.data
        user.username = form.username.data
        user.default_license = form.default_license.data

        user.group_summaries = form.group_summaries.data
        user.summary_frequency = form.summary_frequency.data

        if hasattr(form, "mask_roles"):
            user.mask_roles = form.mask_roles.data

            root = _datastore.find_role("root")
            admin = _datastore.find_role("admin")

            if admin in user.mask_roles and root not in user.mask_roles:
                user.mask_roles.append(root)
        else:
            user.mask_roles = []

        # store Canvas API token if present on form and Canvas integration is enabled
        if main_config.enable_canvas_sync and hasattr(form, "canvas_API_token"):
            user.canvas_API_token = form.canvas_API_token.data
        else:
            # automatically delete for safety
            user.canvas_API_token = None

        fd.academic_title = form.academic_title.data
        fd.use_academic_title = form.use_academic_title.data
        fd.sign_off_students = form.sign_off_students.data
        fd.project_capacity = form.project_capacity.data
        fd.enforce_capacity = form.enforce_capacity.data
        fd.show_popularity = form.show_popularity.data
        fd.dont_clash_presentations = form.dont_clash_presentations.data
        fd.office = form.office.data

        fd.reminder_emails = form.reminder_emails.data
        fd.reminder_frequency = form.reminder_frequency.data

        fd.last_edit_id = current_user.id
        fd.last_edit_timestamp = datetime.now()

        flash("All changes saved", "success")
        log_db_commit(
            f"Updated faculty settings for {current_user.name}",
            user=current_user,
        )

        return home_dashboard()

    else:
        # fill in fields that need data from 'User' and won't have been initialized from obj=data
        if request.method == "GET":
            form.first_name.data = user.first_name
            form.last_name.data = user.last_name
            form.username.data = user.username
            form.default_license.data = user.default_license

            form.group_summaries.data = user.group_summaries
            form.summary_frequency.data = user.summary_frequency

            form.reminder_emails.data = fd.reminder_emails
            form.reminder_frequency.data = fd.reminder_frequency

            if hasattr(form, "mask_roles"):
                form.mask_roles.data = user.mask_roles

            if hasattr(form, "canvas_API_token"):
                form.canvas_API_token.data = user.canvas_API_token

    return render_template_context(
        "faculty/settings.html",
        settings_form=form,
        data=fd,
        enable_canvas=main_config.enable_canvas_sync and fd.is_convenor,
    )


@faculty.route("/past_feedback/<int:student_id>")
@roles_accepted("faculty", "admin", "root")
def past_feedback(student_id):
    """
    Show past feedback associated with this student
    :param student_id:
    :return:
    """
    user: User = User.query.get_or_404(student_id)

    if not user.has_role("student"):
        flash(
            "It is only possible to view past feedback for a student account.", "info"
        )
        return redirect(redirect_url())

    if user.student_data is None:
        flash(
            "Cannot display past feedback for this student account because the corresponding StudentData record is missing.",
            "error",
        )
        return redirect(redirect_url())

    data: StudentData = user.student_data

    if not data.has_previous_submissions:
        flash(
            "This student does not yet have any past feedback. Feedback will be available to view once "
            "the student has made one or more project submissions.",
            "info",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    # collate retired selector and submitter records for this student
    years: List[int]
    selector_records: Dict[List[SelectingStudent]]
    submitter_records: Dict[List[SubmittingStudent]]
    years, selector_records, submitter_records = data.collect_student_records()

    # check roles for logged-in user, to determine whether they are permitted to view the student's feedback
    roles = {}
    for year in submitter_records:
        submissions: List[SubmittingStudent] = submitter_records[year]

        for sub in submissions:
            sub: SubmittingStudent

            for record in sub.ordered_assignments:
                record: SubmissionRecord

                # convenor can always view feedback and documents
                if validate_is_convenor(sub.config.project_class, message=False):
                    roles[record.id] = "convenor"

                # otherwise perform usual check
                elif validate_submission_viewable(record, message=False):
                    roles[record.id] = "faculty"

    student_text = "student feedback"
    generic_text = "student feedback"
    return_url = url_for(
        "faculty.past_feedback", student_id=data.id, text=text, url=url
    )

    return render_template_context(
        "student/timeline.html",
        data=data,
        user=user,
        years=years,
        selector_records={},
        submitter_records=submitter_records,
        roles=roles,
        text=text,
        url=url,
        student_text=student_text,
        generic_text=generic_text,
        return_url=return_url,
    )


def _build_marking_form_class(scheme):
    """
    Dynamically build a WTForms form class from a LiveMarkingScheme.
    Returns a FlaskForm subclass whose fields correspond to the schema.
    """
    from flask_wtf import FlaskForm
    from wtforms import (
        BooleanField,
        FloatField,
        SubmitField,
        TextAreaField,
    )
    from wtforms.validators import InputRequired, NumberRange
    from wtforms.validators import Optional as WTFOptional

    schema = scheme.schema_as_dict
    fields = {}

    for block in schema.get("scheme", []):
        for field_spec in block.get("fields", []):
            key = field_spec["key"]
            ft = field_spec["field_type"]
            ftype = ft["type"]
            default = ft.get("default")
            rows = ft.get("rows", 5)
            label = field_spec["text"]

            if ftype == "boolean":
                fields[key] = BooleanField(
                    label, default=bool(default) if default is not None else False
                )

            elif ftype == "text":
                fields[key] = TextAreaField(
                    label,
                    default=str(default) if default is not None else "",
                    validators=[WTFOptional()],
                    render_kw={"rows": rows},
                )

            elif ftype in ("number", "percent"):
                validators = [InputRequired()]
                if ftype == "percent":
                    mn, mx = 0.0, 100.0
                else:
                    mn = float(ft["min"]) if ft.get("min") is not None else None
                    mx = float(ft["max"]) if ft.get("max") is not None else None
                if mn is not None:
                    validators.append(NumberRange(min=mn))
                if mx is not None:
                    validators.append(NumberRange(max=mx))
                fields[key] = FloatField(
                    label,
                    validators=validators,
                    default=float(default) if default is not None else None,
                )

    if scheme.uses_standard_feedback:
        fields["feedback_positive"] = TextAreaField(
            "What was good?", validators=[WTFOptional()], render_kw={"rows": 7}
        )
        fields["feedback_improvement"] = TextAreaField(
            "What could be improved next time?",
            validators=[WTFOptional()],
            render_kw={"rows": 7},
        )

    fields["submit_marking"] = SubmitField("Submit marking report")
    return type("MarkingForm", (FlaskForm,), fields)


def _can_access_marking_form(report: MarkingReport) -> tuple:
    """
    Returns (is_allowed, is_elevated) where is_elevated means the user is a convenor/admin/root
    who can access the form even when the normal access window has closed.
    """
    from ..shared.validators import validate_is_convenor

    pclass = report.workflow.event.pclass
    is_elevated = validate_is_convenor(pclass, message=False)
    is_role_owner = report.role.user_id == current_user.id

    if is_elevated:
        return True, True
    if is_role_owner:
        return report.marking_form_is_open, False
    return False, False


@faculty.route("/marking_form/<int:report_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def marking_form(report_id):
    """
    Display and process the marking form for a single MarkingReport.
    Accessible to the owning assessor (while marking_form_is_open) and to
    convenors, admins, and root users at any time.
    """
    import json as _json

    report: MarkingReport = MarkingReport.query.get_or_404(report_id)
    workflow: MarkingWorkflow = report.workflow
    event: MarkingEvent = workflow.event
    scheme: LiveMarkingScheme = workflow.scheme
    submitter_report = report.submitter_report
    record: SubmissionRecord = submitter_report.record
    period: SubmissionPeriodRecord = record.period
    pclass: ProjectClass = workflow.event.pclass
    config: ProjectClassConfig = workflow.event.config
    role: SubmissionRole = report.role
    role_user: User = role.user
    submitter: SubmittingStudent = record.owner
    student: StudentData = submitter.student
    student_user: User = student.user

    is_allowed, is_elevated = _can_access_marking_form(report)
    if not is_allowed:
        flash(
            "You do not have access to this marking form, or the form is no longer accepting submissions.",
            "error",
        )
        return redirect(redirect_url())

    if scheme is None:
        flash(
            "This marking workflow has no marking scheme assigned. Please contact the convenor.",
            "error",
        )
        return redirect(redirect_url())

    url = request.args.get("url", url_for("faculty.dashboard"))

    # Build the dynamic form class
    FormClass = _build_marking_form_class(scheme)
    form = FormClass(request.form)

    schema = scheme.schema_as_dict
    is_editable = is_elevated or report.marking_form_is_open

    if form.validate_on_submit() and is_editable:
        # Extract field values from the submitted form
        field_values = {}
        extraction_error = False

        for block in schema.get("scheme", []):
            for field_spec in block.get("fields", []):
                key = field_spec["key"]
                ft = field_spec["field_type"]
                ftype = ft["type"]
                raw_val = getattr(form, key).data

                try:
                    if ftype == "boolean":
                        field_values[key] = bool(raw_val)
                    elif ftype == "text":
                        field_values[key] = str(raw_val) if raw_val is not None else ""
                    elif ftype == "number":
                        val = float(raw_val)
                        precision = ft.get("precision")
                        if precision is not None:
                            val = round(val, int(precision))
                        field_values[key] = val
                    elif ftype == "percent":
                        val = round(float(raw_val), 1)
                        field_values[key] = val
                except (ValueError, TypeError):
                    getattr(form, key).errors.append(
                        "Could not convert this value to the required type."
                    )
                    extraction_error = True

        if not extraction_error:
            # Handle standard feedback fields
            if scheme.uses_standard_feedback:
                report.feedback_positive = form.feedback_positive.data or ""
                report.feedback_improvement = form.feedback_improvement.data or ""

                if (
                    len(report.feedback_positive) > 0
                    and len(report.feedback_improvement) > 0
                ):
                    report.feedback_submitted = True
                    report.feedback_timestamp = datetime.now()

            # Process validation block
            prevent_submit = False
            web_failures = []

            for test_item in schema.get("validation", []):
                test_expr = test_item.get("test", "True")
                actions = test_item.get("action", [])
                message = test_item.get("message", "Validation check failed.")

                try:
                    test_passed = eval(test_expr, {"__builtins__": {}}, field_values)
                except Exception:
                    test_passed = False

                if not test_passed:
                    if "prevent_submit" in actions:
                        flash(message, "error")
                        prevent_submit = True
                    else:
                        if "email" in actions:
                            # Generate validation-failure email workflow
                            try:
                                tmpl = EmailTemplate.find_template_(
                                    EmailTemplate.MARKING_VALIDATION_FAILURE,
                                    pclass_id=pclass.id,
                                )
                                if tmpl is not None:
                                    vf_wf = EmailWorkflow.build_(
                                        name=f"Marking validation failure: report #{report.id}",
                                        template=tmpl,
                                        pclasses=[pclass],
                                    )
                                    db.session.add(vf_wf)
                                    db.session.flush()

                                    for (
                                        notify_user
                                    ) in workflow.notify_on_validation_failure:
                                        item = EmailWorkflowItem.build_(
                                            subject_payload=encode_email_payload(
                                                {
                                                    "report_id": report.id,
                                                    "message": message,
                                                }
                                            ),
                                            body_payload=encode_email_payload(
                                                {
                                                    "report": report,
                                                    "field_values": field_values,
                                                    "message": message,
                                                    "pclass": pclass,
                                                }
                                            ),
                                            recipient_list=[notify_user.email],
                                        )
                                        vf_wf.items.append(item)
                            except Exception as e:
                                current_app.logger.exception(
                                    "Could not create validation failure email workflow",
                                    exc_info=e,
                                )

                        if "web" in actions:
                            web_failures.append(message)

            if not prevent_submit:
                # Evaluate conflation rule to get grade
                conflation_rule = schema.get("conflation_rule", None)
                grade_val = None
                if conflation_rule is not None:
                    try:
                        grade_val = float(
                            eval(conflation_rule, {"__builtins__": {}}, field_values)
                        )
                    except Exception as e:
                        flash(
                            f"Could not evaluate grade from conflation rule. Your report will be saved, but the final value will not have been conflated correctly. Please contact the convenor.",
                            "error",
                        )
                        current_app.logger.error(
                            f'Failed to evaluate conflation rule for MarkingReport #{report.id} -- assessor "{role_user.name}", student "{student_user.name}", for workflow "{workflow.name}", event "{event.name}", submission period "{period.display_name}", project class "{pclass.abbreviation}"'
                        )
                        current_app.logger.error(
                            f'conflation rule = "{conflation_rule}'
                        )
                        current_app.logger.error(f"field_values = {field_values}")

                # Store results
                report_blob = {"fields": field_values}
                if web_failures:
                    report_blob["validation_failures"] = web_failures

                report.report = _json.dumps(report_blob)
                report.report_submitted = True
                report.grade = grade_val
                report.signed_off_id = None
                report.signed_off_timestamp = None
                report.grade_submitted_by_id = current_user.id
                if report.grade_submitted_timestamp is None:
                    report.grade_submitted_timestamp = datetime.now()

                # Schedule close_marking_window to fire 24 hours from now
                from ..tasks.markingevent import schedule_close_marking_window

                schedule_close_marking_window(report)

                try:
                    log_db_commit(
                        f"Submitted marking report for {record.student_identifier['label']} "
                        f"(workflow: {workflow.name})",
                        user=current_user,
                        project_classes=pclass,
                    )
                    if is_elevated:
                        return redirect(url)
                    return render_template_context(
                        "faculty/thankyou_marking.html",
                        dashboard_url=url_for("faculty.dashboard", pane="marking"),
                    )
                except SQLAlchemyError as e:
                    db.session.rollback()
                    current_app.logger.exception(
                        "SQLAlchemyError exception", exc_info=e
                    )
                    flash(
                        "Could not save marking report due to a database error. Please contact a system administrator.",
                        "error",
                    )

    else:
        if request.method == "GET":
            # Pre-populate form with any existing saved values
            existing_blob = {}
            if report.report and report.report != "{}":
                try:
                    existing_blob = _json.loads(report.report).get("fields", {})
                except Exception:
                    pass

            for block in schema.get("scheme", []):
                for field_spec in block.get("fields", []):
                    key = field_spec["key"]
                    if key in existing_blob and hasattr(form, key):
                        getattr(form, key).data = existing_blob[key]

            if scheme.uses_standard_feedback:
                if report.feedback_positive:
                    form.feedback_positive.data = report.feedback_positive
                if report.feedback_improvement:
                    form.feedback_improvement.data = report.feedback_improvement

    # Build journal entries (elevated users only)
    journal_entries = []
    if is_elevated:
        student = record.owner.student
        journal_entries = (
            StudentJournalEntry.query.filter_by(
                student_id=student.id,
                config_year=config.year,
            )
            .order_by(StudentJournalEntry.created_timestamp.desc())
            .all()
        )

    # Build supervision events and attendance data (supervisor roles and elevated users)
    from math import isinf, isnan

    supervision_events = []
    is_supervisor_role = report.role.role in (
        SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
        SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
    )
    attendance_recorded = None
    attendance_missing = None
    attendance_total = None
    attendance_percent = None
    if is_supervisor_role or is_elevated:
        supervision_events = record.events.order_by("time").all()
        attendance_data = record.get_attendance_data()
        attendance_recorded = attendance_data["recorded"]
        attendance_missing = attendance_data["missing"]
        attendance_total = attendance_data["total"]
        _pct = attendance_data["attendance"]
        if _pct is not None and not isnan(_pct) and not isinf(_pct):
            attendance_percent = _pct

    # Filter workflow attachments to those visible to the user's role.
    # ROLE_RESPONSIBLE_SUPERVISOR can also see ROLE_SUPERVISOR attachments (per spec).
    _user_role = report.role.role
    if _user_role == SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR:
        _filter_set = {SubmissionRoleTypesMixin.ROLE_SUPERVISOR, SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR}
    else:
        _filter_set = {_user_role}
    filtered_attachments = [pa for pa in workflow.attachments if pa.has_role_access_for_set(_filter_set)]

    # Prepare LLM feedback suggestions for display on the marking form
    llm_feedback_positive = []
    llm_feedback_improvements = []
    if record.language_analysis_complete:
        _la = record.language_analysis_data
        _fb = _la.get("llm_feedback", {})
        llm_feedback_positive = _fb.get("positive_feedback", []) or []
        llm_feedback_improvements = _fb.get("improvements", []) or []

    return render_template_context(
        "faculty/marking_form.html",
        report=report,
        workflow=workflow,
        scheme=scheme,
        schema=schema,
        record=record,
        period=period,
        pclass=pclass,
        config=config,
        form=form,
        is_editable=is_editable,
        is_elevated=is_elevated,
        is_supervisor_role=is_supervisor_role,
        journal_entries=journal_entries,
        supervision_events=supervision_events,
        attendance_recorded=attendance_recorded,
        attendance_missing=attendance_missing,
        attendance_total=attendance_total,
        attendance_percent=attendance_percent,
        filtered_attachments=filtered_attachments,
        llm_feedback_positive=llm_feedback_positive,
        llm_feedback_improvements=llm_feedback_improvements,
        url=url,
        submit_url=url_for("faculty.marking_form", report_id=report_id, url=url),
    )


@faculty.route("/view_marking_report/<int:report_id>")
@roles_accepted("faculty", "admin", "root")
def view_marking_report(report_id):
    """
    Read-only view of a submitted MarkingReport — shows grade, field values, and feedback.
    Accessible to the role owner (after submission) and to convenors/admins/root.
    """
    import json as _json

    report: MarkingReport = MarkingReport.query.get_or_404(report_id)
    workflow = report.workflow
    scheme = workflow.scheme
    submitter_report = report.submitter_report
    record: SubmissionRecord = submitter_report.record
    period: SubmissionPeriodRecord = record.period
    pclass: ProjectClass = workflow.event.pclass

    from ..models.markingevent import marking_report_to_responsible_supervisors

    is_allowed, is_elevated = _can_access_marking_form(report)
    is_role_owner = report.role.user_id == current_user.id
    is_responsible_supervisor = (
        db.session.query(SubmissionRole)
        .join(
            marking_report_to_responsible_supervisors,
            marking_report_to_responsible_supervisors.c.submission_role_id == SubmissionRole.id,
        )
        .filter(
            marking_report_to_responsible_supervisors.c.marking_report_id == report.id,
            SubmissionRole.user_id == current_user.id,
        )
        .count()
        > 0
    )
    if not is_allowed and not (is_role_owner and report.report_submitted) and not is_responsible_supervisor:
        flash("You do not have permission to view this marking report.", "error")
        return redirect(redirect_url())

    url = request.args.get("url", url_for("faculty.dashboard"))

    schema = scheme.schema_as_dict if scheme else {}
    field_values = {}
    validation_failures = []

    if report.report and report.report != "{}":
        try:
            blob = _json.loads(report.report)
            field_values = blob.get("fields", {})
            validation_failures = blob.get("validation_failures", [])
        except Exception:
            pass

    return render_template_context(
        "faculty/view_marking_report.html",
        report=report,
        workflow=workflow,
        scheme=scheme,
        schema=schema,
        record=record,
        period=period,
        pclass=pclass,
        field_values=field_values,
        validation_failures=validation_failures,
        is_elevated=is_elevated,
        is_responsible_supervisor=is_responsible_supervisor,
        url=url,
        approve_form=ApproveMarkingReportForm(),
    )


@faculty.route("/approve_marking_report/<int:report_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def approve_marking_report(report_id):
    """
    Sign off a MarkingReport on behalf of a ROLE_RESPONSIBLE_SUPERVISOR.
    The signing user must appear in report.responsible_supervisors.
    """
    from datetime import datetime

    from ..models.markingevent import marking_report_to_responsible_supervisors
    from ..tasks.markingevent import advance_submitter_report

    form = ApproveMarkingReportForm(request.form)
    if not form.validate_on_submit():
        flash("Invalid request.", "error")
        return redirect(redirect_url())

    report: MarkingReport = MarkingReport.query.get_or_404(report_id)

    # Find this user's role in the responsible_supervisors collection
    current_role = (
        db.session.query(SubmissionRole)
        .join(
            marking_report_to_responsible_supervisors,
            marking_report_to_responsible_supervisors.c.submission_role_id == SubmissionRole.id,
        )
        .filter(
            marking_report_to_responsible_supervisors.c.marking_report_id == report.id,
            SubmissionRole.user_id == current_user.id,
        )
        .first()
    )
    if current_role is None:
        flash("You do not have permission to approve this marking report.", "error")
        return redirect(redirect_url())

    report.signed_off_id = current_role.id
    report.signed_off_timestamp = datetime.now()
    report.responsible_supervisors.remove(current_role)

    sr = report.submitter_report
    advance_submitter_report(sr)

    try:
        log_db_commit(
            f"Responsible supervisor {current_user.name} signed off MarkingReport #{report.id} "
            f"(workflow: {sr.workflow.name}, student: {sr.student.user.name})",
            user=current_user,
            project_classes=sr.workflow.pclass,
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not approve marking report due to a database error.", "error")
        return redirect(url_for("faculty.view_marking_report", report_id=report.id))

    return redirect(url_for("faculty.thankyou_signoff"))


@faculty.route("/thankyou_signoff")
@roles_accepted("faculty", "admin", "root")
def thankyou_signoff():
    dashboard_url = url_for("faculty.dashboard", pane="signoff")
    return render_template_context("faculty/thankyou_signoff.html", dashboard_url=dashboard_url)


@faculty.route("/thankyou_moderator_report")
@roles_accepted("faculty", "admin", "root")
def thankyou_moderator_report():
    dashboard_url = url_for("faculty.dashboard", pane="moderation")
    return render_template_context("faculty/thankyou_moderator_report.html", dashboard_url=dashboard_url)


@faculty.route("/moderator_report_form/<int:mod_report_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def moderator_report_form(mod_report_id):
    """
    Display and process the moderator report form for a single ModeratorReport.
    Accessible only to the assigned moderator (or elevated users).
    """
    from datetime import datetime

    from flask_wtf import FlaskForm
    from wtforms import DecimalField, SubmitField, TextAreaField
    from wtforms.validators import InputRequired, NumberRange, Optional as WTFOptional

    from ..models.markingevent import SubmitterReportWorkflowStates
    from ..tasks.markingevent import advance_submitter_report

    mod_report: ModeratorReport = ModeratorReport.query.get_or_404(mod_report_id)
    sr = mod_report.submitter_report
    workflow = sr.workflow
    pclass = workflow.event.pclass
    record: SubmissionRecord = sr.record

    is_elevated = current_user.has_role("admin") or current_user.has_role("root") or (
        current_user.faculty_data is not None and current_user.faculty_data.is_convenor_for(pclass)
    )
    is_owner = mod_report.role.user_id == current_user.id

    if not is_elevated and not is_owner:
        flash("You do not have permission to access this moderator report.", "error")
        return redirect(redirect_url())

    url = request.args.get("url", url_for("faculty.dashboard", pane="moderation"))

    class ModeratorReportForm(FlaskForm):
        grade = DecimalField(
            "Recommended grade (%)",
            places=1,
            validators=[InputRequired("Please enter a recommended grade."), NumberRange(min=0, max=100)],
        )
        report = TextAreaField(
            "Justification",
            validators=[WTFOptional()],
            description="Explain your recommended grade, noting any significant discrepancies between the markers.",
        )
        submit = SubmitField("Submit moderator report")

    form = ModeratorReportForm(request.form)

    if form.validate_on_submit():
        mod_report.grade = form.grade.data
        mod_report.report = form.report.data
        mod_report.report_submitted = True
        mod_report.submitted_timestamp = datetime.now()

        if sr.grade is None:
            sr.grade = mod_report.grade
            sr.grade_generated_by_id = current_user.id
            sr.grade_generated_timestamp = datetime.now()
            sr.workflow_state = SubmitterReportWorkflowStates.READY_TO_SIGN_OFF
            sr.accepted_moderator_report_id = mod_report.id
            sr.moderator_accepted_id = mod_report.role_id
            sr.moderator_accepted_timestamp = datetime.now()
        else:
            sr.workflow_state = SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION

        advance_submitter_report(sr)

        try:
            log_db_commit(
                f"Moderator {current_user.name} submitted moderator report for SubmitterReport #{sr.id} "
                f"(workflow: {workflow.name}, student: {sr.student.user.name}, grade: {mod_report.grade})",
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not submit moderator report due to a database error.", "error")
            return redirect(url_for("faculty.moderator_report_form", mod_report_id=mod_report_id))

        return redirect(url_for("faculty.thankyou_moderator_report"))

    # Pre-populate grade if already set
    if request.method == "GET" and mod_report.grade is not None:
        form.grade.data = mod_report.grade
        form.report.data = mod_report.report

    marking_reports = sr.marking_reports.all()
    filtered_attachments = [
        pa for pa in workflow.attachments
        if pa.has_role_access(SubmissionRoleTypesMixin.ROLE_MODERATOR)
    ]

    return render_template_context(
        "faculty/moderator_report_form.html",
        form=form,
        mod_report=mod_report,
        sr=sr,
        workflow=workflow,
        pclass=pclass,
        record=record,
        marking_reports=marking_reports,
        filtered_attachments=filtered_attachments,
        is_elevated=is_elevated,
        url=url,
    )


@faculty.route("/edit_marking_feedback/<int:report_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_marking_feedback(report_id):
    """
    Allow editing of feedback fields (feedback_positive, feedback_improvement) on a submitted
    MarkingReport. Does not recompute the grade. Accessible to the role owner at any time
    after submission, and to convenors/admins/root.
    """
    from flask_wtf import FlaskForm
    from wtforms import SubmitField, TextAreaField
    from wtforms.validators import Optional as WTFOptional

    report: MarkingReport = MarkingReport.query.get_or_404(report_id)
    workflow = report.workflow
    submitter_report = report.submitter_report
    record: SubmissionRecord = submitter_report.record
    period: SubmissionPeriodRecord = record.period
    pclass: ProjectClass = workflow.event.pclass

    is_allowed, is_elevated = _can_access_marking_form(report)
    is_role_owner = report.role.user_id == current_user.id

    if not (is_elevated or is_role_owner):
        flash(
            "You do not have permission to edit feedback for this marking report.",
            "error",
        )
        return redirect(redirect_url())

    if not report.report_submitted and not is_elevated:
        flash(
            "Feedback can only be edited after the marking report has been submitted.",
            "warning",
        )
        return redirect(redirect_url())

    # Build a simple feedback-only form
    FeedbackFormClass = type(
        "MarkingFeedbackForm",
        (FlaskForm,),
        {
            "feedback_positive": TextAreaField(
                "What was good?", validators=[WTFOptional()]
            ),
            "feedback_improvement": TextAreaField(
                "What could be improved next time?", validators=[WTFOptional()]
            ),
            "submit_feedback": SubmitField("Save feedback"),
        },
    )
    form = FeedbackFormClass(request.form)
    url = request.args.get(
        "url", url_for("faculty.view_marking_report", report_id=report_id)
    )

    if form.validate_on_submit():
        report.feedback_positive = form.feedback_positive.data or ""
        report.feedback_improvement = form.feedback_improvement.data or ""
        if len(report.feedback_positive) > 0 and len(report.feedback_improvement) > 0:
            report.feedback_submitted = True
        report.feedback_timestamp = datetime.now()

        # Re-evaluate the parent SubmitterReport lifecycle state
        from ..tasks.markingevent import advance_submitter_report

        advance_submitter_report(submitter_report)

        try:
            log_db_commit(
                f"Updated marking feedback for {record.student_identifier['label']} "
                f"(workflow: {workflow.name})",
                user=current_user,
                project_classes=pclass,
            )
            flash("Feedback updated successfully.", "success")
            return redirect(url)
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save feedback due to a database error.", "error")

    else:
        if request.method == "GET":
            form.feedback_positive.data = report.feedback_positive or ""
            form.feedback_improvement.data = report.feedback_improvement or ""

    return render_template_context(
        "faculty/edit_marking_feedback.html",
        form=form,
        report=report,
        workflow=workflow,
        record=record,
        period=period,
        pclass=pclass,
        url=url,
        submit_url=url_for(
            "faculty.edit_marking_feedback", report_id=report_id, url=url
        ),
    )
