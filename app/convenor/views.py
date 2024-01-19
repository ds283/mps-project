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
from typing import List, Tuple
from uuid import uuid4

import parse
from celery import chain
from celery.result import AsyncResult
from dateutil import parser
from dateutil.relativedelta import relativedelta
from flask import redirect, url_for, flash, request, jsonify, current_app, session, abort
from flask_mailman import EmailMultiAlternatives
from flask_security import roles_accepted, current_user
from ordered_set import OrderedSet
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import with_polymorphic
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.sql import func, literal_column

import app.ajax as ajax
from . import convenor
from .forms import (
    GoLiveFormFactory,
    IssueFacultyConfirmRequestFormFactory,
    OpenFeedbackFormFactory,
    ManualAssignFormFactory,
    AssignPresentationFeedbackFormFactory,
    CustomCATSLimitForm,
    EditPeriodRecordFormFactory,
    ChangeDeadlineFormFactory,
    TestOpenFeedbackForm,
    EditProjectConfigFormFactory,
    AddConvenorStudentTask,
    EditConvenorStudentTask,
    AddConvenorGenericTask,
    EditConvenorGenericTask,
    EditSubmissionPeriodRecordPresentationsForm,
    AddSubmitterRoleForm,
    EditRolesFormFactory,
)
from ..admin.forms import LevelSelectorForm
from ..database import db
from ..documents.forms import UploadPeriodAttachmentForm, EditPeriodAttachmentForm
from ..faculty.forms import (
    AddProjectFormFactory,
    EditProjectFormFactory,
    SkillSelectorForm,
    AddDescriptionFormFactory,
    EditDescriptionSettingsFormFactory,
    MoveDescriptionFormFactory,
    PresentationFeedbackForm,
    SubmissionRoleFeedbackForm,
    SubmissionRoleResponseForm,
    EditDescriptionContentForm,
)
from ..models import (
    User,
    FacultyData,
    StudentData,
    TransferableSkill,
    ProjectClass,
    ProjectClassConfig,
    LiveProject,
    SelectingStudent,
    Project,
    EnrollmentRecord,
    ResearchGroup,
    SkillGroup,
    PopularityRecord,
    FilterRecord,
    DegreeProgramme,
    ProjectDescription,
    SelectionRecord,
    SubmittingStudent,
    SubmissionRecord,
    PresentationFeedback,
    Module,
    FHEQ_Level,
    DegreeType,
    ConfirmRequest,
    SubmissionPeriodRecord,
    WorkflowMixin,
    CustomOffer,
    BackupRecord,
    SubmittedAsset,
    PeriodAttachment,
    Bookmark,
    ConvenorTask,
    ConvenorSelectorTask,
    ConvenorSubmitterTask,
    ConvenorGenericTask,
    SubmissionRole,
    MatchingRecord,
    MatchingRole,
    validate_nonce,
)
from ..shared.actions import do_confirm, do_cancel_confirm, do_deconfirm, do_deconfirm_to_pending
from ..shared.asset_tools import AssetUploadManager
from ..shared.context.convenor_dashboard import (
    get_convenor_dashboard_data,
    get_convenor_todo_data,
    build_convenor_tasks_query,
    get_convenor_approval_data,
    get_capacity_data,
)
from ..shared.context.global_context import render_template_context
from ..shared.convenor import add_selector, add_liveproject, add_blank_submitter
from ..shared.conversions import is_integer
from ..shared.forms.forms import SelectSubmissionRecordFormFactory
from ..shared.projects import create_new_tags, get_filter_list_for_groups_and_skills, project_list_SQL_handler, project_list_in_memory_handler
from ..shared.sqlalchemy import get_count, clone_model
from ..shared.utils import (
    get_current_year,
    home_dashboard,
    get_convenor_filter_record,
    filter_assessors,
    build_enrol_selector_candidates,
    build_enrol_submitter_candidates,
    build_submitters_data,
    redirect_url,
    home_dashboard_url,
)
from ..shared.validators import (
    validate_is_convenor,
    validate_is_administrator,
    validate_edit_project,
    validate_project_open,
    validate_assign_feedback,
    validate_project_class,
    validate_edit_description,
    validate_view_project,
)
from ..student.actions import store_selection
from ..task_queue import register_task
from ..tools import ServerSideSQLHandler, ServerSideInMemoryHandler

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
            <span class="badge bg-warning text-dark">Approval: Queued</span>
        {% elif state == d.WORKFLOW_APPROVAL_REJECTED %}
            <span class="badge bg-info">Approval: In progress</span>
        {% else %}
            <span class="badge bg-danger">Unknown approval state</span>
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


@convenor.route("/status/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def status(id):
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
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    # BUILD FORMS

    # 1. Go Live
    GoLiveForm = GoLiveFormFactory()
    golive_form = GoLiveForm(request.form)

    # 2. Change deadline for project selection
    ChangeDeadlineForm = ChangeDeadlineFormFactory()
    change_form = ChangeDeadlineForm(request.form)

    # 3. Issue faculty confirmation requests
    # change labels and text for issuing confirmation requests depending on current lifecycle state
    if config.requests_issued:
        IssueFacultyConfirmRequestForm = IssueFacultyConfirmRequestFormFactory(
            submit_label="Change deadline", skip_label=None, datebox_label="The current deadline for responses is"
        )
    else:
        IssueFacultyConfirmRequestForm = IssueFacultyConfirmRequestFormFactory(
            submit_label="Issue confirmation requests", skip_label="Skip confirmation step", datebox_label="Deadline"
        )

    issue_form = IssueFacultyConfirmRequestForm(request.form)

    # first time this page is displayed, populate the forms with sensible default data
    if request.method == "GET":
        predicted_deadline = date.today() + timedelta(weeks=6)
        if config.request_deadline is not None:
            issue_form.request_deadline.data = config.request_deadline
        else:
            issue_form.request_deadline.data = predicted_deadline

        if config.live_deadline is not None:
            golive_form.live_deadline.data = config.live_deadline
            change_form.live_deadline.data = config.live_deadline
        else:
            golive_form.live_deadline.data = predicted_deadline
            change_form.live_deadline.data = predicted_deadline

        golive_form.notify_faculty.data = True
        golive_form.notify_selectors.data = True

        change_form.notify_convenor.data = True

    data = get_convenor_dashboard_data(pclass, config)
    todo = get_convenor_todo_data(config)
    approval_data = get_convenor_approval_data(pclass)

    return render_template_context(
        "convenor/dashboard/status.html",
        pane="overview",
        subpane="status",
        golive_form=golive_form,
        change_form=change_form,
        issue_form=issue_form,
        pclass=pclass,
        config=config,
        current_year=current_year,
        convenor_data=data,
        approval_data=approval_data,
        todo=todo,
    )


@convenor.route("/periods/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def periods(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    # get record for current submission period
    period: SubmissionPeriodRecord = config.periods.filter_by(submission_period=config.submission_period).first()
    if period is None and config.submissions > 0:
        flash("Internal error: could not locate SubmissionPeriodRecord. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    # BUILD FORMS

    # 1. Open feedback
    if period is not None and period.is_feedback_open:
        OpenFeedbackForm = OpenFeedbackFormFactory(
            submit_label="Change deadline",
            datebox_label="The current deadline for feedback is",
            include_send_button=True,
            include_test_button=True,
            include_close_button=False,
        )
    else:
        if period.collect_project_feedback:
            OpenFeedbackForm = OpenFeedbackFormFactory(
                submit_label="Open feedback and email markers",
                datebox_label="Deadline",
                include_send_button=False,
                include_test_button=True,
                include_close_button=True,
            )
        else:
            OpenFeedbackForm = OpenFeedbackFormFactory(
                submit_label="Close period", include_send_button=False, include_test_button=False, include_close_button=False
            )

    feedback_form = OpenFeedbackForm(request.form)

    # first time this page is displayed, populate the forms with sensible default data
    if request.method == "GET":
        if period is not None and period.feedback_deadline is not None:
            feedback_form.feedback_deadline.data = period.feedback_deadline
        else:
            feedback_form.feedback_deadline.data = date.today() + timedelta(weeks=3)

        feedback_form.max_attachment.data = 2

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/periods.html",
        pane="overview",
        subpane="periods",
        feedback_form=feedback_form,
        pclass=pclass,
        config=config,
        convenor_data=data,
        today=date.today(),
    )


@convenor.route("/capacity/<int:id>")
@roles_accepted("faculty", "admin", "root")
def capacity(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    # get record for current submission period
    period = config.periods.filter_by(submission_period=config.submission_period).first()
    if period is None and config.submissions > 0:
        flash("Internal error: could not locate SubmissionPeriodRecord. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    data = get_convenor_dashboard_data(pclass, config)
    capacity_data = get_capacity_data(pclass)

    return render_template_context(
        "convenor/dashboard/capacity.html",
        pane="overview",
        subpane="capacity",
        pclass=pclass,
        config=config,
        convenor_data=data,
        capacity_data=capacity_data,
    )


@convenor.route("/attached/<int:id>")
@roles_accepted("faculty", "admin", "root")
def attached(id):
    if id == 0:
        return redirect(url_for("convenor.show_unofferable"))

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
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    valid_filter = request.args.get("valid_filter")

    if valid_filter is None and session.get("convenor_attached_valid_filter"):
        valid_filter = session["convenor_attached_valid_filter"]

    if valid_filter is not None:
        session["convenor_attached_valid_filter"] = valid_filter

    data = get_convenor_dashboard_data(pclass, config)

    # supply list of transferable skill groups and research groups that can be filtered against
    groups, skill_list = get_filter_list_for_groups_and_skills(pclass)

    # get filter record
    filter_record = get_convenor_filter_record(config)

    return render_template_context(
        "convenor/dashboard/attached.html",
        pane="attached",
        pclass=pclass,
        config=config,
        current_year=current_year,
        convenor_data=data,
        groups=groups,
        skill_groups=sorted(skill_list.keys()),
        skill_list=skill_list,
        filter_record=filter_record,
        valid_filter=valid_filter,
    )


@convenor.route("/attached_ajax/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def attached_ajax(id):
    """
    AJAX endpoint for attached projects view
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
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return jsonify({})

    valid_filter = request.args.get("valid_filter")

    # build list of projects attached to this project class
    base_query = db.session.query(Project).filter(Project.project_classes.any(id=id))

    if valid_filter == "valid" or valid_filter == "not-valid" or valid_filter == "reject" or valid_filter == "pending":
        if pclass.require_confirm:
            base_query = base_query.join(ProjectDescription, ProjectDescription.parent_id == Project.id).filter(
                ProjectDescription.project_classes.any(id=pclass.id)
            )

            if valid_filter == "pending":
                base_query = base_query.filter(ProjectDescription.confirmed == False)

        if valid_filter == "valid":
            base_query = base_query.filter(
                ProjectDescription.workflow_state != ProjectDescription.WORKFLOW_APPROVAL_QUEUED,
                ProjectDescription.workflow_state != ProjectDescription.WORKFLOW_APPROVAL_REJECTED,
            )

        if valid_filter == "not-valid":
            base_query = base_query.filter(ProjectDescription.workflow_state == ProjectDescription.WORKFLOW_APPROVAL_QUEUED)

        if valid_filter == "reject":
            base_query = base_query.filter(ProjectDescription.workflow_state == ProjectDescription.WORKFLOW_APPROVAL_REJECTED)

    # restrict query to projects owned by active users, or generic projects
    base_query = base_query.join(User, User.id == Project.owner_id, isouter=True).filter(or_(Project.generic == True, User.active == True))

    # get FilterRecord for currently logged-in user
    filter_record: FilterRecord = get_convenor_filter_record(config)

    valid_group_ids = [g.id for g in filter_record.group_filters]
    valid_skill_ids = [s.id for s in filter_record.skill_filters]

    if pclass.advertise_research_group and len(valid_group_ids) > 0:
        base_query = base_query.filter(Project.group_id.in_(valid_group_ids))

    if len(valid_skill_ids) > 0:
        base_query = base_query.filter(Project.skills.any(TransferableSkill.id.in_(valid_skill_ids)))

    return project_list_SQL_handler(
        request,
        base_query,
        current_user_id=current_user.id,
        config=config,
        menu_template="convenor",
        name_labels=True,
        text="attached projects list",
        url=url_for("convenor.attached", id=id),
        show_approvals=True,
        show_errors=True,
    )


@convenor.route("/faculty/<int:id>")
@roles_accepted("faculty", "admin", "root")
def faculty(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    enroll_filter = request.args.get("enroll_filter")
    state_filter = request.args.get("state_filter")

    if state_filter == "no-projects":
        enroll_filter = "enrolled"

    if enroll_filter is None and session.get("convenor_faculty_enroll_filter"):
        enroll_filter = session["convenor_faculty_enroll_filter"]

    if enroll_filter is not None:
        session["convenor_faculty_enroll_filter"] = enroll_filter

    if state_filter is None and session.get("convenor_faculty_state_filter"):
        state_filter = session["convenor_faculty_state_filter"]

    if state_filter is not None:
        session["convenor_faculty_state_filter"] = state_filter

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/faculty.html",
        pane="faculty",
        subpane="list",
        pclass=pclass,
        config=config,
        current_year=current_year,
        faculty=faculty,
        convenor_data=data,
        enroll_filter=enroll_filter,
        state_filter=state_filter,
    )


@convenor.route("faculty_ajax/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def faculty_ajax(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    enroll_filter = request.args.get("enroll_filter")
    state_filter = request.args.get("state_filter")

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return jsonify({})

    if enroll_filter == "enrolled":
        # build a list of only enrolled faculty, together with their FacultyData records
        faculty_ids = db.session.query(EnrollmentRecord.owner_id).filter(EnrollmentRecord.pclass_id == id).subquery()

        # get User, FacultyData pairs for this list
        base_query = (
            db.session.query(User, FacultyData)
            .filter(User.active)
            .join(FacultyData, FacultyData.id == User.id)
            .join(faculty_ids, User.id == faculty_ids.c.owner_id)
        )

    elif enroll_filter == "not-enrolled":
        # build a list of only enrolled faculty, together with their FacultyData records
        faculty_ids = db.session.query(EnrollmentRecord.owner_id).filter(EnrollmentRecord.pclass_id == id).subquery()

        # join to main User and FacultyData records and select pairs that have no counterpart in faculty_ids
        base_query = (
            db.session.query(User, FacultyData)
            .filter(User.active)
            .join(FacultyData, FacultyData.id == User.id)
            .join(faculty_ids, faculty_ids.c.owner_id == User.id, isouter=True)
            .filter(faculty_ids.c.owner_id == None)
        )

    elif (
        ((enroll_filter == "supv-active" or enroll_filter == "supv-sabbatical" or enroll_filter == "supv-exempt") and pclass.uses_supervisor)
        or ((enroll_filter == "mark-active" or enroll_filter == "mark-sabbatical" or enroll_filter == "mark-exempt") and pclass.uses_marker)
        or ((enroll_filter == "pres-active" or enroll_filter == "pres-sabbatical" or enroll_filter == "pres-exempt") and pclass.uses_presentations)
    ):
        faculty_ids = db.session.query(EnrollmentRecord.owner_id).filter(EnrollmentRecord.pclass_id == id)

        if enroll_filter == "supv-active":
            faculty_ids = faculty_ids.filter(EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED)
        elif enroll_filter == "supv-sabbatical":
            faculty_ids = faculty_ids.filter(EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_SABBATICAL)
        elif enroll_filter == "supv-exempt":
            faculty_ids = faculty_ids.filter(EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_EXEMPT)
        elif enroll_filter == "mark-active":
            faculty_ids = faculty_ids.filter(EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_ENROLLED)
        elif enroll_filter == "mark-sabbatical":
            faculty_ids = faculty_ids.filter(EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_SABBATICAL)
        elif enroll_filter == "mark-exempt":
            faculty_ids = faculty_ids.filter(EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_EXEMPT)
        elif enroll_filter == "pres-active":
            faculty_ids = faculty_ids.filter(EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED)
        elif enroll_filter == "pres-sabbatical":
            faculty_ids = faculty_ids.filter(EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_SABBATICAL)
        elif enroll_filter == "pres-exempt":
            faculty_ids = faculty_ids.filter(EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_EXEMPT)

        faculty_ids_q = faculty_ids.subquery()

        # get User, FacultyData pairs for this list
        base_query = (
            db.session.query(User, FacultyData)
            .filter(User.active)
            .join(FacultyData, FacultyData.id == User.id)
            .join(faculty_ids_q, User.id == faculty_ids_q.c.owner_id)
        )

    else:
        # build list of all active faculty, together with their FacultyData records
        base_query = db.session.query(User, FacultyData).filter(User.active).join(FacultyData, FacultyData.id == User.id)

    return _faculty_ajax_handler(base_query, pclass, config, state_filter)


def _faculty_ajax_handler(base_query, pclass: ProjectClass, config: ProjectClassConfig, state_filter: str):
    def search_name(row: Tuple[User, FacultyData]):
        u, fd = row
        u: User
        fd: FacultyData

        return u.name

    def sort_name(row: Tuple[User, FacultyData]):
        u, fd = row
        u: User
        fd: FacultyData

        return [u.last_name, u.first_name]

    def search_email(row: Tuple[User, FacultyData]):
        u, fd = row
        u: User
        fd: FacultyData

        return u.email

    def sort_email(row: Tuple[User, FacultyData]):
        u, fd = row
        u: User
        fd: FacultyData

        return u.email

    def sort_enrolled(row: Tuple[User, FacultyData]):
        u, fd = row
        u: User
        fd: FacultyData

        er: EnrollmentRecord = fd.get_enrollment_record(pclass)
        if er is None:
            return 0

        count = 0
        if er.supervisor_state == er.SUPERVISOR_ENROLLED:
            count += 1
        if er.marker_state == er.MARKER_ENROLLED:
            count += 1
        if er.presentations_state == er.PRESENTATIONS_ENROLLED:
            count += 1

        return count

    def sort_golive(row: Tuple[User, FacultyData]):
        u, fd = row
        u: User
        fd: FacultyData

        return config.require_confirm and config.requests_issued and config.is_confirmation_required(fd)

    def sort_projects(row: Tuple[User, FacultyData]):
        u, fd = row
        u: User
        fd: FacultyData

        return fd.number_projects_offered(pclass)

    name = {"search": search_name, "order": sort_name}
    email = {"search": search_email, "order": sort_email}
    enrolled = {"order": sort_enrolled}
    golive = {"order": sort_golive}
    projects = {"order": sort_projects}

    columns = {"name": name, "email": email, "enrolled": enrolled, "golive": golive, "projects": projects}

    def _filter(state_filter: str, pclass: ProjectClass, row):
        u, fd = row
        u: User
        fd: FacultyData

        if state_filter == "no-projects" and pclass.uses_supervisor:
            return fd.number_projects_offered(pclass) == 0

        if state_filter == "no-marker" and pclass.uses_marker:
            return fd.number_assessor == 0

        if state_filter == "unofferable":
            return fd.projects_unofferable > 0

        if state_filter == "custom-cats":
            return _has_custom_CATS(fd, pclass)

        return True

    with ServerSideInMemoryHandler(request, base_query, columns, row_filter=partial(_filter, state_filter, pclass)) as handler:
        return handler.build_payload(partial(ajax.convenor.faculty_data, pclass, config))


def _has_custom_CATS(fac_data, pclass):
    record: EnrollmentRecord = fac_data.get_enrollment_record(pclass)

    if record is None:
        return False

    return (
        record.CATS_supervision is not None
        or record.CATS_marking is not None
        or record.CATS_moderation is not None
        or record.CATS_presentation is not None
    )


@convenor.route("/selectors/<int:id>")
@roles_accepted("faculty", "admin", "root")
def selectors(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    convert_filter = request.args.get("convert_filter")
    year_filter = request.args.get("year_filter")
    match_filter = request.args.get("match_filter")
    match_show = request.args.get("match_show")

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    # build a list of live students selecting from this project class
    selectors = config.selecting_students.filter_by(retired=False).all()

    # build list of available cohorts and degree programmes
    cohorts = set()
    years = set()
    programmes = set()
    for sel in selectors:
        cohorts.add(sel.student.cohort)

        academic_year = sel.academic_year
        if academic_year is not None:
            years.add(academic_year)

        programmes.add(sel.student.programme_id)

    # build list of available programmes
    all_progs = (
        db.session.query(DegreeProgramme)
        .filter(DegreeProgramme.active == True)
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
        .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())
        .all()
    )
    progs = [rec for rec in all_progs if rec.id in programmes]

    if cohort_filter is None and session.get("convenor_selectors_cohort_filter"):
        cohort_filter = session["convenor_selectors_cohort_filter"]

    if isinstance(cohort_filter, str) and cohort_filter != "all" and int(cohort_filter) not in cohorts:
        cohort_filter = "all"

    if cohort_filter is not None:
        session["convenor_selectors_cohort_filter"] = cohort_filter

    if prog_filter is None and session.get("convenor_selectors_prog_filter"):
        prog_filter = session["convenor_selectors_prog_filter"]

    if isinstance(prog_filter, str) and prog_filter != "all" and int(prog_filter) not in programmes:
        prog_filter = "all"

    if prog_filter is not None:
        session["convenor_selectors_prog_filter"] = prog_filter

    if state_filter is None and session.get("convenor_selectors_state_filter"):
        state_filter = session["convenor_selectors_state_filter"]

    if isinstance(state_filter, str) and state_filter not in ["all", "submitted", "bookmarks", "none", "confirmations", "twd"]:
        state_filter = "all"

    if state_filter is not None:
        session["convenor_selectors_state_filter"] = state_filter

    if convert_filter is None and session.get("convenor_selectors_convert_filter"):
        convert_filter = session["convenor_selectors_convert_filter"]

    if isinstance(convert_filter, str) and convert_filter not in ["all", "convert", "no-convert"]:
        convert_filter = "all"

    if convert_filter is not None:
        session["convenor_selectors_convert_filter"] = convert_filter

    if year_filter is None and session.get("convenor_selectors_year_filter"):
        year_filter = session["convenor_selectors_year_filter"]

    if isinstance(year_filter, str) and year_filter != "all" and int(year_filter) not in years:
        year_filter = "all"

    if year_filter is not None:
        session["convenor_selectors_year_filter"] = year_filter

    # get list of current published matchings (if any) that include this project type;
    # these can be used to filter for students that are/are not included in the matching
    if config.has_published_matches:
        matches = config.published_matches.all()
        match_ids = [x.id for x in matches]
    else:
        matches = None

    if match_filter is None and session.get("convenor_selectors_match_filter"):
        match_filter = session["convenor_selectors_match_filter"]

    if match_show is None and session.get("convenor_selectors_match_show"):
        match_show = session["convenor_selectors_match_show"]

    if matches is None:
        match_filter = "all"
        match_show = "all"
    else:
        if isinstance(match_filter, str) and match_filter != "all" and int(match_filter) not in match_ids:
            match_filter = "all"
            match_show = "all"

    if match_show not in ["all", "included", "missing"]:
        match_show = "all"

    if match_filter is not None:
        session["convenor_selectors_match_filter"] = match_filter

    if match_show is not None:
        session["convenor_selectors_match_show"] = match_show

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/selectors.html",
        pane="selectors",
        subpane="list",
        pclass=pclass,
        config=config,
        convenor_data=data,
        current_year=current_year,
        cohorts=sorted(cohorts),
        progs=progs,
        years=sorted(years),
        matches=matches,
        match_filter=match_filter,
        match_show=match_show,
        cohort_filter=cohort_filter,
        prog_filter=prog_filter,
        state_filter=state_filter,
        year_filter=year_filter,
        convert_filter=convert_filter,
    )


@convenor.route("/selectors_ajax/<int:id>")
@roles_accepted("faculty", "admin", "root")
def selectors_ajax(id):
    """
    Ajax data point for selectors view
    :param id:
    :return:
    """
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    convert_filter = request.args.get("convert_filter")
    year_filter = request.args.get("year_filter")
    match_filter = request.args.get("match_filter")
    match_show = request.args.get("match_show")

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return jsonify({})

    data = _build_selector_data(config, cohort_filter, prog_filter, state_filter, convert_filter, year_filter, match_filter, match_show)

    return ajax.convenor.selectors_data(data, config)


def _build_selector_data(config, cohort_filter, prog_filter, state_filter, convert_filter, year_filter, match_filter, match_show):
    # build a list of live students selecting from this project class
    selectors: List[SelectingStudent] = config.selecting_students.filter_by(retired=False)

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)
    year_flag, year_value = is_integer(year_filter)
    match_flag, match_value = is_integer(match_filter)

    if cohort_flag or prog_flag:
        selectors = selectors.join(StudentData, StudentData.id == SelectingStudent.student_id)

    if cohort_flag:
        selectors = selectors.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        selectors = selectors.filter(StudentData.programme_id == prog_value)

    if convert_filter == "convert":
        selectors = selectors.filter(SelectingStudent.convert_to_submitter == True)
    elif convert_filter == "no-convert":
        selectors = selectors.filter(SelectingStudent.convert_to_submitter == False)

    if state_filter == "submitted":
        data = [rec for rec in selectors.all() if rec.has_submitted]
    elif state_filter == "bookmarks":
        data = [rec for rec in selectors.all() if not rec.has_submitted and rec.has_bookmarks]
    elif state_filter == "none":
        data = [rec for rec in selectors.all() if not rec.has_submitted and not rec.has_bookmarks]
    elif state_filter == "confirmations":
        data = [rec for rec in selectors.all() if rec.number_pending > 0]
    elif state_filter == "twd":
        data = [rec for rec in selectors.all() if rec.student.intermitting]
    else:
        data = selectors.all()

    if year_flag:
        data = [s for s in data if (s.academic_year is None or s.academic_year == year_value)]

    if match_flag:
        match = config.published_matches.filter_by(id=match_value).first()

        if match is not None:
            # get list of student ids that are included in the match
            student_set = set(x.selector.student_id for x in match.records)

            if match_show == "included":
                data = [s for s in data if s.student_id in student_set]
            elif match_show == "missing":
                data = [s for s in data if s.student_id not in student_set]

    return data


@convenor.route("/enrol_selectors/<int:id>")
@roles_accepted("faculty", "admin", "root")
def enrol_selectors(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    if (
        not (current_user.has_role("admin") or current_user.has_role("root"))
        and config.selector_lifecycle >= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING
    ):
        flash("Manual enrolment of selectors is only possible before student choices are closed", "error")
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")

    if prog_filter is None and session.get("convenor_sel_enroll_prog_filter"):
        prog_filter = session["convenor_sel_enroll_prog_filter"]

    candidates = build_enrol_selector_candidates(
        config, disable_programme_filter=True if isinstance(prog_filter, str) and prog_filter.lower() == "off" else False
    )

    # build list of available cohorts and degree programmes
    cohorts = set()
    years = set()
    programmes = set()
    for student in candidates:
        cohorts.add(student.cohort)
        programmes.add(student.programme_id)

        academic_year = student.academic_year
        if academic_year is not None:
            years.add(academic_year)

    # build list of available programmes
    all_progs = (
        db.session.query(DegreeProgramme)
        .filter(DegreeProgramme.active == True)
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
        .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())
        .all()
    )
    progs = [rec for rec in all_progs if rec.id in programmes]

    if cohort_filter is None and session.get("convenor_sel_enroll_cohort_filter"):
        cohort_filter = session["convenor_sel_enroll_cohort_filter"]

    if isinstance(cohort_filter, str) and cohort_filter != "all" and int(cohort_filter) not in cohorts:
        cohort_filter = "all"

    if cohort_filter is not None:
        session["convenor_sel_enroll_cohort_filter"] = cohort_filter

    if isinstance(prog_filter, str) and prog_filter != "all" and prog_filter != "off" and int(prog_filter) not in programmes:
        prog_filter = "all"

    if prog_filter is not None:
        session["convenor_sel_enroll_prog_filter"] = prog_filter

    if year_filter is None and session.get("convenor_sel_enroll_year_filter"):
        year_filter = session["convenor_sel_enroll_year_filter"]

    if isinstance(year_filter, str) and year_filter != "all" and int(year_filter) not in years:
        year_filter = "all"

    if year_filter is not None:
        session["convenor_sel_enroll_year_filter"] = year_filter

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/enrol_selectors.html",
        pane="selectors",
        subpane="enroll",
        pclass=pclass,
        config=config,
        convenor_data=data,
        cohorts=sorted(cohorts),
        progs=progs,
        years=sorted(years),
        cohort_filter=cohort_filter,
        prog_filter=prog_filter,
        year_filter=year_filter,
    )


@convenor.route("/enrol_selectors_ajax/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def enrol_selectors_ajax(id):
    """
    Ajax data point for enroll selectors view
    :param id:
    :return:
    """
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return jsonify({})

    if (
        not (current_user.has_role("admin") or current_user.has_role("root"))
        and config.selector_lifecycle >= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING
    ):
        return jsonify({})

    disable = True if (isinstance(prog_filter, str) and prog_filter.lower() == "off") else False
    candidates = build_enrol_selector_candidates(config, disable_programme_filter=disable)

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)
    year_flag, year_value = is_integer(year_filter)

    if cohort_flag:
        candidates = candidates.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        candidates = candidates.filter(StudentData.programme_id == prog_value)
    elif prog_filter.lower() == "all":
        candidates = candidates.filter(or_(StudentData.programme_id == p.id for p in pclass.programmes))

    if not year_flag:
        # use SQL server-side handler for performance if it is possible
        # (we can't use SQL to filter by the available years because this also tests for students that have
        # graduated)
        return _enrol_selectors_ajax_handler(request, candidates, config)

    return _enrol_selectors_ajax_handler(request, candidates, config, year_value)


def _filter_candidates(year: int, row: StudentData):
    if row.has_graduated:
        return False

    if year is None or row.academic_year is None:
        return True  # to avoid not offering students who should be visible

    if row.academic_year != year:
        return False

    return True


def _enrol_selectors_ajax_handler(request, candidates, config: ProjectClassConfig, year_value: int = None):
    def search_name(row: StudentData):
        u: User = row.user
        return u.name

    def sort_name(row: StudentData):
        u: User = row.user
        return [u.last_name, u.first_name]

    def search_programme(row: StudentData):
        p: DegreeProgramme = row.programme
        return p.name

    def sort_programme(row: StudentData):
        p: DegreeProgramme = row.programme
        return p.name

    def search_cohort(row: StudentData):
        return str(row.cohort)

    def sort_cohort(row: StudentData):
        return row.cohort

    def search_current_year(row: StudentData):
        return str(row.academic_year)

    def sort_current_year(row: StudentData):
        return row.academic_year

    name = {"search": search_name, "order": sort_name}
    programme = {"search": search_programme, "order": sort_programme}
    cohort = {"search": search_cohort, "order": sort_cohort}
    current_year = {"search": search_current_year, "order": sort_current_year}

    columns = {"name": name, "programme": programme, "cohort": cohort, "current_year": current_year}

    with ServerSideInMemoryHandler(request, candidates, columns, row_filter=partial(_filter_candidates, year_value)) as handler:
        return handler.build_payload(partial(ajax.convenor.enrol_selectors_data, config))


@convenor.route("/enroll_all_selectors/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def enrol_all_selectors(configid):
    config = ProjectClassConfig.query.get_or_404(configid)
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if (
        not (current_user.has_role("admin") or current_user.has_role("root"))
        and config.selector_lifecycle >= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING
    ):
        flash("Manual enrolment of selectors is only possible before student choices are closed", "error")
        return redirect(redirect_url())

    convert = bool(int(request.args.get("convert", 1)))

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")

    candidates = build_enrol_selector_candidates(
        config, disable_programme_filter=True if isinstance(prog_filter, str) and prog_filter.lower() == "off" else False
    )

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)
    year_flag, year_value = is_integer(year_filter)

    if cohort_flag:
        candidates = candidates.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        candidates = candidates.filter(StudentData.programme_id == prog_value)

    candidate_values = candidates.all()

    year = year_value if year_flag else None
    c_list = [x for x in candidate_values if _filter_candidates(year, x)]

    for c in c_list:
        add_selector(c, configid, convert=convert, autocommit=False)

    try:
        db.session.commit()
        flash('Added {count} selectors to project "{proj}"'.format(count=len(candidate_values), proj=config.project_class.name), "info")
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not add selectors because a database error occurred. Please check the logs for further information.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/enrol_selector/<int:sid>/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def enrol_selector(sid, configid):
    """
    Manually enroll a student as a selector
    :param sid:
    :param configid:
    :return:
    """
    config = ProjectClassConfig.query.get_or_404(configid)
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if (
        not (current_user.has_role("admin") or current_user.has_role("root"))
        and config.selector_lifecycle >= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING
    ):
        flash("Manual enrolment of selectors is only possible before student choices are closed", "error")
        return redirect(redirect_url())

    convert = bool(int(request.args.get("convert", 1)))

    add_selector(sid, configid, convert=convert, autocommit=True)

    return redirect(redirect_url())


@convenor.route("/delete_selector/<int:sid>")
@roles_accepted("faculty", "admin", "root")
def delete_selector(sid):
    """
    Manually delete a selector
    :param sid:
    :return:
    """
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    if (
        not (current_user.has_role("admin") or current_user.has_role("root"))
        and sel.config.selector_lifecycle > ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN
    ):
        flash("Manual deletion of selectors is only possible before student choices are closed", "error")
        return redirect(redirect_url())

    if sel.has_bookmarks or sel.has_submitted or sel.has_matches:
        url = request.args.get("url", None)
        if url is None:
            url = redirect_url()

        title = 'Delete selector "{name}"'.format(name=sel.student.user.name)
        panel_title = 'Delete selector <i class="fas fa-user-circle"></i> <strong>{name}</strong>'.format(name=sel.student.user.name)

        action_url = url_for("convenor.do_delete_selector", sid=sid, url=url)
        message = (
            '<p>Are you sure that you wish to delete selector <i class="fas fa-user-circle"></i> <strong>{name}</strong>?</p>'
            "<p>This selector has stored bookmarks, submitted a list of project choices, or has been included "
            "in a matching.</p>"
            "<p>This action cannot be undone. Any bookmarks and submitted preferences will be lost, and "
            "the selector will be deleted from any matches of which they are currently part.</p>".format(name=sel.student.user.name)
        )
        submit_label = "Delete selector"

        return render_template_context(
            "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
        )

    try:
        # delete should cascade to Bookmark and SelectionRecord items; also, no need to remove
        # matching_records elements because we are guaranteed that there aren't any
        db.session.delete(sel)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not delete selector due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/do_delete_selector/<int:sid>")
@roles_accepted("faculty", "admin", "root")
def do_delete_selector(sid):
    """
    Manually delete a selector -- action step
    :param sid:
    :return:
    """
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    if (
        not (current_user.has_role("admin") or current_user.has_role("root"))
        and sel.config.selector_lifecycle > ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN
    ):
        flash("Manual deletion of selectors is only possible before student choices are closed", "error")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    try:
        sel.detach_records()
        db.session.delete(sel)

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not delete selector due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@convenor.route("/selector_grid/<int:id>")
@roles_accepted("faculty", "admin", "root")
def selector_grid(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")
    state_filter = request.args.get("state_filter")
    match_filter = request.args.get("match_filter")
    match_show = request.args.get("match_show")

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        flash("The selector grid view is available only after student choices are closed", "error")
        return redirect(redirect_url())

    # build a list of live students selecting from this project class
    selectors = config.selecting_students.filter_by(retired=False).all()

    # build list of available cohorts and degree programmes
    cohorts = set()
    programmes = set()
    years = set()
    for sel in selectors:
        cohorts.add(sel.student.cohort)

        academic_year = sel.academic_year
        if academic_year is not None:
            years.add(academic_year)

        programmes.add(sel.student.programme_id)

    # build list of available programmes
    all_progs = (
        db.session.query(DegreeProgramme)
        .filter(DegreeProgramme.active == True)
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
        .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())
        .all()
    )
    progs = [rec for rec in all_progs if rec.id in programmes]
    groups = db.session.query(ResearchGroup).filter_by(active=True).order_by(ResearchGroup.name.asc()).all()

    if cohort_filter is None and session.get("convenor_sel_grid_cohort_filter"):
        cohort_filter = session["convenor_sel_grid_cohort_filter"]

    if cohort_filter is not None:
        session["convenor_sel_grid_cohort_filter"] = cohort_filter

    if prog_filter is None and session.get("convenor_sel_grid_prog_filter"):
        prog_filter = session["convenor_sel_grid_prog_filter"]

    if prog_filter is not None:
        session["convenor_sel_grid_prog_filter"] = prog_filter

    if year_filter is None and session.get("convenor_sel_grid_year_filter"):
        year_filter = session["convenor_sel_grid_year_filter"]

    if isinstance(year_filter, str) and year_filter != "all" and int(year_filter) not in years:
        year_filter = "all"

    if year_filter is not None:
        session["convenor_sel_grid_filter"] = year_filter

    if state_filter is None and session.get("convenor_sel_grid_state_filter"):
        state_filter = session["convenor_sel_grid_state_filter"]

    if isinstance(state_filter, str) and state_filter not in ["all", "twd"]:
        state_filter = "all"

    if state_filter is not None:
        session["convenor_sel_grid_state_filter"] = state_filter

    # get list of current published matchings (if any) that include this project type;
    # these can be used to filter for students that are/are not included in the matching
    if config.has_published_matches:
        matches = config.published_matches.all()
        match_ids = [x.id for x in matches]
    else:
        matches = None

    if match_filter is None and session.get("convenor_sel_grid_match_filter"):
        match_filter = session["convenor_sel_grid_match_filter"]

    if match_show is None and session.get("convenor_sel_grid_match_show"):
        match_show = session["convenor_sel_grid_match_show"]

    if matches is None:
        match_filter = "all"
        match_show = "all"
    else:
        if isinstance(match_filter, str) and match_filter != "all" and int(match_filter) not in match_ids:
            match_filter = "all"
            match_show = "all"

    if match_show not in ["all", "included", "missing"]:
        match_show = "all"

    if match_filter is not None:
        session["convenor_sel_grid_match_filter"] = match_filter

    if match_show is not None:
        session["convenor_sel_grid_match_show"] = match_show

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/selector_grid.html",
        pane="selectors",
        subpane="grid",
        pclass=pclass,
        config=config,
        convenor_data=data,
        current_year=current_year,
        cohorts=sorted(cohorts),
        progs=progs,
        years=sorted(years),
        matches=matches,
        match_filter=match_filter,
        match_show=match_show,
        cohort_filter=cohort_filter,
        prog_filter=prog_filter,
        year_filter=year_filter,
        groups=groups,
        state_filter=state_filter,
    )


@convenor.route("/selector_grid_ajax/<int:id>")
@roles_accepted("faculty", "admin", "root")
def selector_grid_ajax(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")
    state_filter = request.args.get("state_filter")
    match_filter = request.args.get("match_filter")
    match_show = request.args.get("match_show")

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return jsonify({})

    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        return jsonify({})

    # build a list of live students selecting from this project class
    selectors: List[SelectingStudent] = config.selecting_students.filter_by(retired=False)

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)
    year_flag, year_value = is_integer(year_filter)
    match_flag, match_value = is_integer(match_filter)

    if cohort_flag or prog_flag or state_filter != "all":
        selectors = selectors.join(StudentData, StudentData.id == SelectingStudent.student_id)

    if state_filter == "twd":
        selectors = selectors.filter(StudentData.intermitting == True)

    if cohort_flag:
        selectors = selectors.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        selectors = selectors.filter(StudentData.programme_id == prog_value)

    if year_flag:
        data = [s for s in selectors.all() if (s.academic_year is None or s.academic_year == year_value)]
    else:
        data = selectors.all()

    # for selection_open_to_all type project classes (eg. RP), no need to include students who did not respond
    if pclass.selection_open_to_all:
        data = [s for s in data if s.has_submitted or s.has_bookmarks]

    if match_flag:
        match = config.published_matches.filter_by(id=match_value).first()

        if match is not None:
            # get list of student ids that are included in the match
            student_set = set(x.selector.student_id for x in match.records)

            if match_show == "included":
                data = [s for s in data if s.student_id in student_set]
            elif match_show == "missing":
                data = [s for s in data if s.student_id not in student_set]

    return ajax.convenor.selector_grid_data(data, config)


@convenor.route("/show_confirmations/<int:id>")
@roles_accepted("faculty", "admin", "root")
def show_confirmations(id):
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
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN:
        flash("The outstanding confirmations view is available only after student choices have opened", "error")
        return redirect(redirect_url())

    if config.selector_lifecycle >= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        flash("The outstanding confirmations view is not available after student choices have closed", "error")
        return redirect(redirect_url())

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/show_confirmations.html",
        pane="selectors",
        subpane="confirm",
        pclass=pclass,
        config=config,
        convenor_data=data,
        current_year=current_year,
    )


@convenor.route("/show_confirmations_ajax/<int:id>")
@roles_accepted("faculty", "admin", "root")
def show_confirmations_ajax(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return jsonify({})

    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN:
        return jsonify({})

    if config.selector_lifecycle >= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        return jsonify({})

    outstanding = (
        db.session.query(ConfirmRequest)
        .filter(or_(ConfirmRequest.state == ConfirmRequest.REQUESTED, ConfirmRequest.state == ConfirmRequest.DECLINED))
        .join(LiveProject, LiveProject.id == ConfirmRequest.project_id)
        .filter(LiveProject.config_id == config.id)
        .all()
    )

    return ajax.convenor.show_confirmations(outstanding, pclass.id)


@convenor.route("/submitters/<int:id>")
@roles_accepted("faculty", "admin", "root")
def submitters(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    year_filter = request.args.get("year_filter")
    data_display = request.args.get("data_display")

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    submitters = config.submitting_students.filter_by(retired=False).all()

    # build list of available cohorts and degree programmes
    cohorts = set()
    years = set()
    programmes = set()
    for sub in submitters:
        cohorts.add(sub.student.cohort)

        academic_year = sub.academic_year
        if academic_year is not None:
            years.add(academic_year)

        programmes.add(sub.student.programme_id)

    # build list of available programmes
    all_progs = (
        db.session.query(DegreeProgramme)
        .filter(DegreeProgramme.active == True)
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
        .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())
        .all()
    )
    progs = [rec for rec in all_progs if rec.id in programmes]

    if cohort_filter is None and session.get("convenor_submitters_cohort_filter"):
        cohort_filter = session["convenor_submitters_cohort_filter"]

    if isinstance(cohort_filter, str) and cohort_filter != "all" and int(cohort_filter) not in cohorts:
        cohort_filter = "all"

    if cohort_filter is not None:
        session["convenor_submitters_cohort_filter"] = cohort_filter

    if prog_filter is None and session.get("convenor_submitters_prog_filter"):
        prog_filter = session["convenor_submitters_prog_filter"]

    if isinstance(prog_filter, str) and prog_filter != "all" and int(prog_filter) not in programmes:
        prog_filter = "all"

    if prog_filter is not None:
        session["convenor_submitters_prog_filter"] = prog_filter

    if state_filter is None and session.get("convenor_submitters_state_filter"):
        state_filter = session["convenor_submitters_state_filter"]

    if isinstance(state_filter, str) and state_filter not in [
        "all",
        "published",
        "unpublished",
        "late-feedback",
        "no-late-feedback",
        "not-started",
        "report",
        "no-report",
        "attachments",
        "no-attachments",
        "twd",
    ]:
        state_filter = "all"

    if state_filter is not None:
        session["convenor_submitters_state_filter"] = state_filter

    if year_filter is None and session.get("convenor_submitters_year_filter"):
        year_filter = session["convenor_submitters_year_filter"]

    if isinstance(year_filter, str) and year_filter != "all" and int(year_filter) not in years:
        year_filter = "all"

    if year_filter is not None:
        session["convenor_submitters_year_filter"] = year_filter

    if data_display is None and session.get("convenor_submitters_data_display"):
        data_display = session["convenor_submitters_data_display"]

    if isinstance(data_display, str) and data_display not in ["name", "number", "both-name", "both-number"]:
        data_display = "name"

    if data_display is not None:
        session["convenor_submitters_data_display"] = data_display

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/submitters.html",
        pane="submitters",
        subpane="list",
        pclass=pclass,
        config=config,
        convenor_data=data,
        current_year=current_year,
        cohorts=sorted(cohorts),
        progs=progs,
        years=sorted(years),
        cohort_filter=cohort_filter,
        prog_filter=prog_filter,
        state_filter=state_filter,
        year_filter=year_filter,
        data_display=data_display,
    )


@convenor.route("/submitters_ajax/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def submitters_ajax(id):
    """
    Ajax data point for submitters view
    """
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return jsonify({})

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    year_filter = request.args.get("year_filter")
    data_display = request.args.get("data_display")

    show_name = True
    show_number = False
    sort_number = False

    if data_display == "number":
        show_name = False
        show_number = True
        sort_number = True
    elif data_display == "both-name":
        show_number = True
    elif data_display == "both-number":
        show_number = True
        sort_number = True

    data = build_submitters_data(config, cohort_filter, prog_filter, state_filter, year_filter)

    return ajax.convenor.submitters_data(data, config, show_name, show_number, sort_number)


@convenor.route("/enrol_submitters/<int:id>")
@roles_accepted("faculty", "admin", "root")
def enrol_submitters(id):
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
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    if config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash("Manual enrolment of selectors is no longer possible at this stage in the project lifecycle.", "error")
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")

    candidates = build_enrol_submitter_candidates(config)

    # build list of available cohorts and degree programmes
    cohorts = set()
    years = set()
    programmes = set()
    for student in candidates:
        cohorts.add(student.cohort)
        programmes.add(student.programme_id)

        academic_year = student.academic_year
        if academic_year is not None:
            years.add(academic_year)

    # build list of available programmes
    all_progs = (
        db.session.query(DegreeProgramme)
        .filter(DegreeProgramme.active == True)
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)
        .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())
        .all()
    )
    progs = [rec for rec in all_progs if rec.id in programmes]

    if cohort_filter is None and session.get("convenor_sub_enroll_cohort_filter"):
        cohort_filter = session["convenor_sub_enroll_cohort_filter"]

    if cohort_filter is not None:
        session["convenor_sel_enroll_cohort_filter"] = cohort_filter

    if cohort_filter is not None:
        session["convenor_sub_enroll_cohort_filter"] = cohort_filter

    if prog_filter is None and session.get("convenor_sub_enroll_prog_filter"):
        prog_filter = session["convenor_sub_enroll_prog_filter"]

    if isinstance(prog_filter, str) and prog_filter != "all" and int(prog_filter) not in programmes:
        prog_filter = "all"

    if prog_filter is not None:
        session["convenor_sub_enroll_prog_filter"] = prog_filter

    if year_filter is None and session.get("convenor_sub_enroll_year_filter"):
        year_filter = session["convenor_sub_enroll_year_filter"]

    if isinstance(year_filter, str) and year_filter != "all" and int(year_filter) not in years:
        year_filter = "all"

    if year_filter is not None:
        session["convenor_sub_enroll_year_filter"] = year_filter

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/enrol_submitters.html",
        pane="submitters",
        subpane="enroll",
        pclass=pclass,
        config=config,
        convenor_data=data,
        current_year=current_year,
        cohorts=sorted(cohorts),
        progs=progs,
        years=sorted(years),
        cohort_filter=cohort_filter,
        prog_filter=prog_filter,
        year_filter=year_filter,
    )


@convenor.route("/enrol_submitters_ajax/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def enrol_submitters_ajax(id):
    """
    Ajax data point for enroll submitters view
    :param id:
    :return:
    """

    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return jsonify({})

    if config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        return jsonify({})

    candidates = build_enrol_submitter_candidates(config)

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)
    year_flag, year_value = is_integer(year_filter)

    if cohort_flag:
        candidates = candidates.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        candidates = candidates.filter(StudentData.programme_id == prog_value)

    if year_flag:
        candidates = [s for s in candidates.all() if s.academic_year is None or (not s.has_graduated and s.academic_year == year_value)]
    else:
        candidates = candidates.all()

    return ajax.convenor.enrol_submitters_data(candidates, config)


@convenor.route("/enroll_all_submitters/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def enrol_all_submitters(configid):
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(configid)
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if config.submitter_lifecycle > ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY:
        flash("Manual enrolment of submitters is only possible during normal project activity", "error")
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    year_filter = request.args.get("year_filter")

    # get current year
    current_year = get_current_year()
    old_config: ProjectClassConfig = config.project_class.get_config(config.year - 1)

    candidates = build_enrol_submitter_candidates(config)

    # filter by cohort and programme if required
    cohort_flag, cohort_value = is_integer(cohort_filter)
    prog_flag, prog_value = is_integer(prog_filter)
    year_flag, year_value = is_integer(year_filter)

    if cohort_flag:
        candidates = candidates.filter(StudentData.cohort == cohort_value)

    if prog_flag:
        candidates = candidates.filter(StudentData.programme_id == prog_value)

    if year_flag:
        candidates = [s for s in candidates.all() if (s.academic_year is None or s.academic_yea == year_value)]
    else:
        candidates = candidates.all()

    for c in candidates:
        add_blank_submitter(c, old_config.id if old_config is not None else None, configid, autocommit=False)

    try:
        db.session.commit()
        flash('Added {count} submitters to project "{proj}"'.format(count=len(candidates), proj=config.project_class.name), "info")
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not add submitters because a database error occurred. Please check the logs for further information.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/enrol_submitter/<int:sid>/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def enrol_submitter(sid, configid):
    """
    Manually enroll a student as a submitter
    :param sid:
    :param configid:
    :return:
    """
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(configid)
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    # return 404 if student does not exist
    student: StudentData = StudentData.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if config.submitter_lifecycle > ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY:
        if not validate_is_administrator(message=False):
            flash(
                "Manual enrolment of submitters is only possible during normal project activity. "
                "Please contact an administrator to perform this operation.",
                "error",
            )
            return redirect(redirect_url())

    old_config: ProjectClassConfig = config.project_class.get_config(config.year - 1)

    add_blank_submitter(student, old_config.id if old_config is not None else None, configid, autocommit=True)

    return redirect(redirect_url())


@convenor.route("/delete_submitter/<int:sid>")
@roles_accepted("faculty", "admin", "root")
def delete_submitter(sid):
    """
    Manually delete a submitter -- confirmation step
    :param sid:
    :return:
    """
    sub: SubmittingStudent = SubmittingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sub.config.project_class):
        return redirect(redirect_url())

    if sub.config.submitter_lifecycle > ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY:
        flash("Manual deletion of submitters is only possible during normal project activity", "error")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    title = 'Delete submitter "{name}"'.format(name=sub.student.user.name)
    panel_title = 'Delete submitter <i class="fas fa-user-circle"></i> <strong>{name}</strong>'.format(name=sub.student.user.name)

    action_url = url_for("convenor.do_delete_submitter", sid=sid, url=url)
    message = (
        '<p>Are you sure that you wish to delete submitter <i class="fas fa-user-circle"></i> <strong>{name}</strong>?</p>'
        "<p>This action cannot be undone.</p>".format(name=sub.student.user.name)
    )
    submit_label = "Delete submitter"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@convenor.route("/do_delete_submitter/<int:sid>")
@roles_accepted("faculty", "admin", "root")
def do_delete_submitter(sid):
    """
    Manually delete a submitter -- action step
    :param sid:
    :return:
    """
    sub: SubmittingStudent = SubmittingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sub.config.project_class):
        return redirect(redirect_url())

    if sub.config.submitter_lifecycle > ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY:
        flash("Manual deletion of submitters is only possible during normal project activity", "error")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    try:
        sub.detach_records()
        db.session.delete(sub)

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        flash('Could not delete submitter due to a database error ("{n}"). Please contact a system ' "administrator.".format(n=e), "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@convenor.route("/delete_all_submitters/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def delete_all_submitters(configid):
    """
    Delete all submitters -- confirmation step
    :param configid:
    :return:
    """
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(configid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if config.submitter_lifecycle > ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY:
        flash("Manual deletion of submitters is only possible during normal project activity", "error")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    title = "Delete all submitters"
    panel_title = "Delete all submitters"

    action_url = url_for("convenor.do_delete_all_submitters", configid=configid, url=url)
    message = "<p>Are you sure that you wish to delete <strong>all submitters</strong>?" "<p>This action cannot be undone.</p>"
    submit_label = "Delete all submitters"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@convenor.route("/do_delete_all_submitters/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def do_delete_all_submitters(configid):
    """
    Delete all submitters -- action step
    :param sid:
    :return:
    """
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(configid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if config.submitter_lifecycle > ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY:
        flash("Manual deletion of submitters is only possible during normal project activity", "error")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    try:
        submitter_list = config.submitting_students

        for item in submitter_list:
            item.detach_records()
            db.session.delete(item)

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        flash('Could not delete all submitters due to a database error ("{n}"). Please contact a system ' "administrator.".format(n=e), "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@convenor.route("/edit_roles/<int:sub_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_roles(sub_id):
    # sub_id is a SubmittingStudent instance
    sub: SubmittingStudent = SubmittingStudent.query.get_or_404(sub_id)
    config: ProjectClassConfig = sub.config
    pclass: ProjectClass = config.project_class
    student: StudentData = sub.student
    user: User = student.user

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    EditRolesForm = EditRolesFormFactory(config)
    form = EditRolesForm(request.form)

    # determine whether a specific SubmissionRecord instance has been provided, otherwise use the one from the
    # selector form, or default to the current submission period
    record_id = request.args.get("record_id", None)
    if record_id is not None:
        record: SubmissionRecord = SubmissionRecord.query.get_or_404(record_id)

        # check that record actually belongs to the specified SubmittingStudent instance
        if record.owner_id != sub.id:
            flash(
                "Cannot edit roles for this combination of submitter and submission record, "
                "because the specified submission record does not belong to the student.",
                "error",
            )
            return redirect(redirect_url())
    else:
        if hasattr(form, "selector") and form.selector.data is not None:
            record: SubmissionRecord = sub.get_assignment(period=form.selector.data)
        else:
            record = sub.get_assignment()

    period: SubmissionPeriodRecord = record.period

    if hasattr(form, "selector"):
        form.selector.data = period

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    if url is None and text is None:
        url = url_for("convenor.submitters", id=pclass.id)
        text = "convenor submitters view"

    return render_template_context(
        "convenor/submitter/edit_roles.html",
        form=form,
        pclass=pclass,
        config=config,
        record=record,
        sub=sub,
        student=student,
        user=user,
        period=period,
        url=url,
        text=text,
    )


@convenor.route("edit_roles_ajax/<int:record_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_roles_ajax(record_id):
    # sub_id is a SubmissionRecord instance
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(record_id)

    sub: SubmittingStudent = record.owner
    period: SubmissionPeriodRecord = record.period
    config: ProjectClassConfig = period.config
    pclass: ProjectClass = config.project_class

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    if url is None and text is None:
        url = url_for("convenor.submitters", id=pclass.id)
        text = "convenor submitters view"

    base_query = record.roles.join(User, User.id == SubmissionRole.user_id)

    name = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "order": [User.last_name, User.first_name],
        "search_collation": "urf8_general_ci",
    }
    role = {"order": SubmissionRole.role}

    columns = {"name": name, "role": role}

    with ServerSideSQLHandler(request, base_query, columns) as handler:

        def row_formatter(roles):
            return ajax.convenor.edit_roles(roles, return_url=url_for("convenor.edit_roles", sub_id=sub.id, record_id=record.id, url=url, text=text))

        return handler.build_payload(row_formatter)


@convenor.route("/delete_role/<int:role_id>")
@roles_accepted("faculty", "admin", "root")
def delete_role(role_id):
    # role_id is a SubmissionRole
    role = SubmissionRole.query.get_or_404(role_id)

    record: SubmissionRecord = role.submission
    sub: SubmittingStudent = record.owner
    student: StudentData = sub.student
    sub_user: User = student.user
    role_user: User = role.user
    period: SubmissionPeriodRecord = record.period
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)

    if url is None:
        url = url_for(
            "convenor.edit_roles",
            sub_id=sub.id,
            record_id=record.id,
            url=url_for("convenor.submitters", id=config.project_class.id, text="convenor submitters view"),
        )

    title = "Delete role"
    panel_title = 'Delete {type} role for <i class="fas fa-user-circle"></i> ' "<strong>{name}</strong>".format(
        type=role.role_label, name=sub_user.name
    )

    action_url = url_for("convenor.perform_delete_role", role_id=role_id, url=url)
    message = (
        "<p>Please confirm that you wish to delete the {type} role for "
        '<i class="fas fa-user-circle"></i> <strong>{role_name}</strong> '
        'belonging to submitter <i class="fas fa-user-circle"></i> <strong>{user_name}</strong>.</p>'
        "<p>This action cannot be undone.</p>".format(type=role.role_label, role_name=role_user.name, user_name=sub_user.name)
    )
    submit_label = "Delete role"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@convenor.route("/perform_delete_role/<int:role_id>")
@roles_accepted("faculty", "admin", "root")
def perform_delete_role(role_id):
    # role_id is a SubmissionRole
    role = SubmissionRole.query.get_or_404(role_id)

    record: SubmissionRecord = role.submission
    sub: SubmittingStudent = record.owner
    period: SubmissionPeriodRecord = record.period
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)

    if url is None:
        url = url_for("convenor.edit_roles", sub_id=sub.id, record_id=record.id)

    try:
        db.session.delete(role)

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not delete role due to a database error. Please contact a system administrator", "error")

    return redirect(url)


@convenor.route("/add_role/<int:record_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def add_role(record_id):
    # sub_id is a SubmissionRecord instance
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(record_id)

    sub: SubmittingStudent = record.owner
    period: SubmissionPeriodRecord = record.period
    config: ProjectClassConfig = period.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)

    if url is None:
        url = url_for(
            "convenor.edit_roles",
            sub_id=sub.id,
            record_id=record.id,
            url=url_for("convenor.submitters", id=config.project_class.id, text="convenor submitters view"),
        )

    form = AddSubmitterRoleForm(request.form)
    form._record = record

    if form.validate_on_submit():
        role = SubmissionRole(
            role=form.role.data,
            user=form.user.data.user,
            submission_id=record.id,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
            last_edit_id=None,
            last_edit_timestamp=None,
        )

        try:
            db.session.add(role)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not add new role due to a database error. Please contact a system administrator", "error")

        return redirect(url)

    return render_template_context("convenor/submitter/add_role.html", form=form, record=record, period=period, config=config, sub=sub, url=url)


@convenor.route("/liveprojects/<int:id>")
@roles_accepted("faculty", "admin", "root")
def liveprojects(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    state_filter = request.args.get("state_filter")

    if state_filter is None and session.get("convenor_liveprojects_state_filter"):
        state_filter = session["convenor_liveprojects_state_filter"]

    if state_filter is not None:
        session["convenor_liveprojects_state_filter"] = state_filter

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
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

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return jsonify({})

    base_query = config.live_projects.join(User, User.id == LiveProject.owner_id, isouter=True)

    # get FilterRecord for currently logged-in user
    filter_record = get_convenor_filter_record(config)

    valid_group_ids = [g.id for g in filter_record.group_filters]
    valid_skill_ids = [s.id for s in filter_record.skill_filters]

    if pclass.advertise_research_group and len(valid_group_ids) > 0:
        base_query = base_query.filter(Project.group_id.in_(valid_group_ids))

    if len(valid_skill_ids) > 0:
        base_query = base_query.filter(Project.skills.any(TransferableSkill.id.in_(valid_skill_ids)))

    return _liveprojects_ajax_handler(base_query, config, state_filter)


def _liveprojects_ajax_handler(base_query, config: ProjectClassConfig, state_filter: str):
    if state_filter == "submitter":
        base_query = base_query.filter(func.count(LiveProject.submitted) > 0)
    elif state_filter == "bookmarks":
        base_query = base_query.filter(and_(func.count(LiveProject.selections) == 0, func.count(LiveProject.bookmarks) > 0))
    elif state_filter == "none":
        base_query = base_query.filter(and_(func.count(LiveProject.selections) == 0, func.count(LiveProject.bookmarks) == 0))
    elif state_filter == "confirmations":
        base_query = (
            base_query.join(ConfirmRequest, ConfirmRequest.project_id == LiveProject.id, isouter=True)
            .filter(ConfirmRequest.state == ConfirmRequest.REQUESTED)
            .distinct()
        )

    name = {"search": LiveProject.name, "order": LiveProject.name, "search_collation": "utf8_general_ci"}
    owner = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "order": [User.last_name, User.first_name],
        "search_collation": "utf8_general_ci",
    }
    bookmarks = {"order": func.count(LiveProject.bookmarks)}
    selections = {"order": func.count(LiveProject.selections)}
    # confirmations = {'order': func.count(LiveProject.confirmation_requests.filter_by(state=ConfirmRequest.REQUESTED))}

    columns = {"name": name, "owner": owner, "bookmarks": bookmarks, "selections": selections}

    # def sort_popularity(row: LiveProject):
    #     data = row.popularity_rank(live=True)
    #
    #     if data is None:
    #         return -1
    #
    #     rank, total = data
    #     return rank

    with ServerSideSQLHandler(request, base_query, columns) as handler:

        def row_formatter(liveprojects):
            return ajax.convenor.liveprojects_data(
                liveprojects, config, url=url_for("convenor.liveprojects", id=config.pclass_id), text="convenor LiveProjects view"
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
        flash('Cannot delete live project "{name}" because it is marked as not removable.'.format(name=project.name), "error")
        return redirect(redirect_url())

    # if this config has closed selections, we cannot delete any live projects
    if config.selection_closed:
        flash(
            'Cannot delete LiveProjects belonging to class "{cls}" in the {yra}-{yrb} cycle, '
            "because selections have already closed".format(cls=config.name, yra=config.submit_year_a, yrb=config.submit_year_b),
            "info",
        )
        return redirect(redirect_url())

    title = 'Delete LiveProject "{name}" for project class "{cls}" in ' "{yra}&ndash;{yrb}".format(
        name=project.name, cls=config.name, yra=config.submit_year_a, yrb=config.submit_year_b
    )
    action_url = url_for("convenor.perform_delete_live_project", pid=pid)
    message = (
        '<p>Please confirm that you wish to delete the live project "{name}" belonging to '
        'project class "{cls}" {yra}&ndash;{yrb}.</p>'
        "<p>This action cannot be undone.</p>".format(name=project.name, cls=config.name, yra=config.submit_year_a, yrb=config.submit_year_b)
    )
    submit_label = "Delete live project"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=title, action_url=action_url, message=message, submit_label=submit_label
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
        flash('Cannot delete live project "{name}" because it is marked as undeletable.'.format(name=project.name), "error")
        return redirect(redirect_url())

    # if this config has closed selections, we cannot delete any live projects
    if config.selection_closed:
        flash(
            'Cannot delete LiveProjects belonging to class "{cls}" in the {yra}-{yrb} cycle, '
            "because selections have already closed".format(cls=config.name, yra=config.submit_year_a, yrb=config.submit_year_b),
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
            'Could not delete live project "{name}" because of a database error. ' "Please contact a system administrator.".format(name=project.name),
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
            "because selections have already closed".format(cls=config.name, yra=config.submit_year_a, yrb=config.submit_year_b),
            "info",
        )
        return redirect(redirect_url())

    try:
        project.hidden = True
        db.session.commit()

    except SQLAlchemyError as e:
        flash(
            'Could not hide live project "{name}" because of a database error. ' "Please contact a system administrator.".format(name=project.name),
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
            "because selections have already closed".format(cls=config.name, yra=config.submit_year_a, yrb=config.submit_year_b),
            "info",
        )
        return redirect(redirect_url())

    try:
        project.hidden = False
        db.session.commit()

    except SQLAlchemyError as e:
        flash(
            'Could not unhide live project "{name}" because of a database error. ' "Please contact a system administrator.".format(name=project.name),
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
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    # reject if project class is not live
    if not config.live:
        flash("Manual attachment of projects is only possible after Go Live for this academic year", "error")
        return redirect(redirect_url())

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/attach_liveproject.html", pane="live", subpane="attach", pclass=pclass, config=config, convenor_data=data
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

    # get existing liveprojects
    current_projects = [p.parent_id for p in config.live_projects]

    # compute all active attached projects that do not have a LiveProject equivalent
    base_query = pclass.projects.filter(Project.active == True)

    # don't show attached projects
    base_query = base_query.filter(Project.id.not_in(current_projects))

    # restrict query to projects owned by active users, or generic projects
    base_query = base_query.join(User, User.id == Project.owner_id, isouter=True).filter(or_(Project.generic == True, User.active == True))

    # remove projects that don't have a description
    base_query = base_query.join(ProjectDescription, ProjectDescription.parent_id == Project.id).filter(
        ProjectDescription.project_classes.any(id=pclass.id)
    )

    return project_list_SQL_handler(
        request,
        base_query,
        current_user_id=current_user.id,
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
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(configid)

    # reject user if not entitled to act as convenor
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class is not live
    if not config.live:
        flash("Manual attachment of projects is only possible after Go Live for this academic year", "error")
        return redirect(redirect_url())

    # reject if desired project is not attachable
    project: Project = Project.query.get_or_404(id)

    if config.project_class not in project.project_classes:
        flash(
            'Project "{p}" is not attached to "{c}". You do not have sufficient privileges to manually attach it. '
            "Please consult with an administrator.".format(p=project.name, c=config.name),
            "error",
        )
        return redirect(redirect_url())

    desc: ProjectDescription = project.get_description(config.project_class)
    if desc is None:
        flash('Project "{p}" does not have a description for "{c}" and cannot be ' "attached.".format(p=project.name, c=config.name))
        return redirect(redirect_url())

    # get number for this project
    number = config.live_projects.count() + 1

    add_liveproject(number, project, configid, autocommit=True)

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
    base_query = db.session.query(Project, ProjectDescription).filter(ProjectDescription.parent_id == Project.id).filter(Project.active == True)

    # get existing liveprojects attached to this config instance
    current_projects = [p.parent_id for p in config.live_projects]

    # don't show these existing attached liveprojects
    base_query = base_query.filter(Project.id.not_in(current_projects))

    # don't offer to attach projects attached to this project class
    base_query = base_query.filter(~Project.project_classes.any(ProjectClass.id == pclass.id))

    # restrict query to projects owned by active users, or generic projects
    base_query = base_query.join(User, User.id == Project.owner_id, isouter=True).filter(or_(Project.generic == True, User.active == True))

    return project_list_SQL_handler(
        request,
        base_query,
        current_user_id=current_user.id,
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
        flash("Manual attachment of projects is only possible after Go Live for this academic year", "error")
        return redirect(redirect_url())

    # get number for this project
    desc: ProjectDescription = ProjectDescription.query.get_or_404(id)
    number = config.live_projects.count() + 1

    add_liveproject(number, desc.parent, configid, desc=desc, autocommit=True)

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
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    status_filter = request.args.get("status_filter")

    if status_filter is None and session.get("convenor_todo_list_status_filter"):
        status_filter = session["convenor_todo_list_status_filter"]

    if status_filter is not None and status_filter not in ["default", "overdue", "available", "dropped", "completed"]:
        status_filter = "default"

    if status_filter is not None:
        session["convenor_todo_list_status_filter"] = status_filter

    blocking_filter = request.args.get("blocking_filter")

    if blocking_filter is None and session.get("convenor_todo_list_blocking_filter"):
        blocking_filter = session["convenor_todo_list_blocking_filter"]

    if blocking_filter is not None and blocking_filter not in ["all", "blocking", "not-blocking"]:
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

    base_query = build_convenor_tasks_query(config, status_filter=status_filter, blocking_filter=blocking_filter, due_date_order=False)

    # set up columns for server-side processing;
    # use column literals because the query returned from base_query is likely to be built using
    # polymorphic objects
    task = {"search": literal_column("description"), "order": literal_column("description"), "search_collation": "utf8_general_ci"}
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
        "order": literal_column("(NOT(complete OR dropped) * (100*(due_date > CURDATE()) + 50*(defer_date > CURDATE())) + 10*complete + 1*dropped)")
    }

    columns = {"task": task, "defer_date": defer_date, "due_date": due_date, "status": status}

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
            flash("Could not create new task due to a database error. Please contact a system administrator", "error")

        return redirect(url)

    return render_template_context("convenor/tasks/edit_generic_task.html", form=form, url=url, config=config)


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
            flash("Could not save changes to task due to a database error. Please contact a system administrator", "error")

        return redirect(url)

    return render_template_context("convenor/tasks/edit_generic_task.html", form=form, url=url, task=task, config=config)


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

    return render_template_context("convenor/edit_descriptions.html", project=project, pclass_id=pclass_id, create=create)


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
        pclass: ProjectClass = db.session.query(ProjectClass).filter_by(id=pclass_id).first()

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
        descs, _desc_label, _desc_menu, pclass_id=pclass_id, create=create, config=config, desc_validator=validate_edit_description
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
    AddProjectForm = AddProjectFormFactory(convenor_editing=True, uses_tags=True, uses_research_groups=True)
    form = AddProjectForm(request.form)

    if form.validate_on_submit():
        tag_list = create_new_tags(form)
        project = Project(
            name=form.name.data,
            tags=tag_list,
            active=True,
            owner=form.owner.data if not form.generic.data else None,
            generic=form.generic.data,
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

        if pclass_id != 0 and len(project.project_classes.all()) == 0 and not pclass.uses_supervisor:
            project.project_classes.append(pclass)

        # ensure that list of preferred degree programmes is consistent
        project.validate_programmes()

        try:
            db.session.add(project)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not add new project due to a database error. Please contact a system administrator", "error")

        # auto-enroll if implied by current project class associations
        if not project.generic:
            owner = project.owner
            assert owner is not None

            for pclass in project.project_classes:
                if not owner.is_enrolled(pclass):
                    owner.add_enrollment(pclass)
                    flash("Auto-enrolled {name} in {pclass}".format(name=project.owner.user.name, pclass=pclass.name))

        if form.submit.data:
            return redirect(url_for("convenor.edit_descriptions", id=project.id, pclass_id=pclass_id, create=1))
        elif form.save_and_exit.data:
            return redirect(url_for("convenor.attached", id=pclass_id))
        elif form.save_and_preview:
            return redirect(
                url_for("faculty.project_preview", id=project.id, text="attached projects list", url=url_for("convenor.attached", id=pclass_id))
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

    return render_template_context("faculty/edit_project.html", project_form=form, pclass_id=pclass_id, title="Add new project")


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
        url = url_for("convenor.attached", id=pclass_id)
        text = "attached projects view"

    # set up form
    project: Project = Project.query.get_or_404(id)

    EditProjectForm = EditProjectFormFactory(convenor_editing=True, uses_tags=True, uses_research_groups=True)
    form = EditProjectForm(obj=project)
    form.project = project

    if form.validate_on_submit():
        tag_list = create_new_tags(form)

        project.name = form.name.data
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

        if pclass_id != 0 and len(project.project_classes.all()) == 0 and not pclass.uses_supervisor:
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
                        flash("Auto-enrolled {name} in {pclass}".format(name=project.owner.user.name, pclass=pclass.name))

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes to project due to a database error. Please contact a system administrator", "error")

        return redirect(url)

    return render_template_context(
        "faculty/edit_project.html", project_form=form, project=project, pclass_id=pclass_id, title="Edit project details", url=url, text=text
    )


@convenor.route("/activate_project/<int:id>/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def activate_project(id, pclass_id):
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

    proj.enable()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not activate project due to a database error. Please contact a system administrator", "error")

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
        flash("Could not deactivate project due to a database error. Please contact a system administrator", "error")

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
            flash("Could not add new project description due to a database error. Please contact a system administrator", "error")

        return redirect(url_for("convenor.edit_descriptions", id=pid, pclass_id=pclass_id, create=create))

    return render_template_context(
        "faculty/edit_description.html", project=proj, form=form, pclass_id=pclass_id, title="Add new description", create=create, unique_id=uuid4()
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
        url = url_for("convenor.edit_descriptions", id=desc.parent_id, pclass_id=pclass_id, create=create)
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
            flash("Could not edit project description due to a database error. Please contact a system administrator", "error")

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


@convenor.route("/edit_description_content/<int:did>/<int:pclass_id>", methods=["GET", "POST"])
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
        url = url_for("convenor.edit_descriptions", id=desc.parent_id, pclass_id=pclass_id, create=create)
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
            flash("Could not edit project description due to a database error. Please contact a system administrator", "error")

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


@convenor.route("/description_modules/<int:did>/<int:pclass_id>/<int:level_id>", methods=["GET", "POST"])
@convenor.route("/description_modules/<int:did>/<int:pclass_id>", methods=["GET", "POST"])
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
            form.selector.data = FHEQ_Level.query.filter(FHEQ_Level.active == True).order_by(FHEQ_Level.numeric_level.asc()).first()
        else:
            form.selector.data = FHEQ_Level.query.filter(FHEQ_Level.active == True, FHEQ_Level.id == level_id).first()

    # get list of modules for the current level_id
    if form.selector.data is not None:
        modules = desc.get_available_modules(level_id=form.selector.data.id)
    else:
        modules = []

    level_id = form.selector.data.id if form.selector.data is not None else None
    levels = FHEQ_Level.query.filter_by(active=True).order_by(FHEQ_Level.numeric_level.asc()).all()

    return render_template_context(
        "convenor/description_modules.html",
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


@convenor.route("/description_attach_module/<int:did>/<int:pclass_id>/<int:mod_id>/<int:level_id>")
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
                    'Could not attach module "{name}" due to a database error. ' "Please contact a system administrator".format(name=module.name),
                    "error",
                )

        else:
            flash('Could not attach module "{name}" because it is already attached.'.format(name=module.name), "warning")

    else:
        flash(
            'Could not attach module "{name}" because it cannot be applied as a pre-requisite '
            "for this description. Most likely this means it is incompatible with one of the selected "
            "project classes. Consider generating a new variant for the incompatible "
            "classes.".format(name=module.name),
            "warning",
        )

    return redirect(url_for("convenor.description_modules", did=did, pclass_id=pclass_id, level_id=level_id, create=create))


@convenor.route("/description_detach_module/<int:did>/<int:pclass_id>/<int:mod_id>/<int:level_id>")
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
                'Could not detach module "{name}" due to a database error. ' "Please contact a system administrator".format(name=module.name), "error"
            )

    else:
        flash('Could not detach specified module "{name}" because it was not previously ' "attached.".format(name=module.name), "warning")

    return redirect(url_for("convenor.description_modules", did=did, pclass_id=pclass_id, level_id=level_id, create=create))


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
        flash("Could not delete project description due to a database error. Please contact a system administrator", "error")

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

        if ProjectDescription.query.filter_by(parent_id=desc.parent_id, label=new_label).first() is None:
            break

        suffix += 1

    if suffix >= 100:
        flash('Could not duplicate variant "{label}" because a new unique label could not ' "be generated".format(label=desc.label), "error")
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
        flash("Could not duplicate project description due to a database error. Please contact a system administrator", "error")

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

    MoveDescriptionForm = MoveDescriptionFormFactory(old_project.owner_id, old_project.id, pclass_id=pclass_id)
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

                elif get_count(new_project.descriptions.filter(ProjectDescription.project_classes.any(id=pclass.id))) > 0:
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
                flash('Variant "{name}" successfully moved to project ' '"{pname}"'.format(name=desc.label, pname=new_project.name), "info")
            except SQLAlchemyError as e:
                db.session.rollback()
                flash('Variant "{name}" could not be moved due to a database error'.format(name=desc.label), "error")
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        else:
            flash('Variant "{name}" could not be moved because its parent project is ' "missing".format(name=desc.label), "error")

        if create:
            return redirect(url_for("convenor.edit_descriptions", id=old_project.id, pclass_id=pclass_id, create=True))
        else:
            return redirect(url_for("convenor.edit_descriptions", id=new_project.id, pclass_id=pclass_id))

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
            form.selector.data = SkillGroup.query.filter(SkillGroup.active == True).order_by(SkillGroup.name.asc()).first()
        else:
            form.selector.data = SkillGroup.query.filter(SkillGroup.active == True, SkillGroup.id == sel_id).first()

    # get list of active skills matching selector
    if form.selector.data is not None:
        skills = TransferableSkill.query.filter(TransferableSkill.active == True, TransferableSkill.group_id == form.selector.data.id).order_by(
            TransferableSkill.name.asc()
        )
    else:
        skills = TransferableSkill.query.filter_by(active=True).order_by(TransferableSkill.name.asc())

    create = request.args.get("create", default=None)

    return render_template_context(
        "convenor/attach_skills.html", data=proj, skills=skills, pclass_id=pclass_id, form=form, sel_id=form.selector.data.id, create=create
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

    return redirect(url_for("convenor.attach_skills", id=projectid, pclass_id=pclass_id, sel_id=sel_id, create=create))


@convenor.route("/remove_skill/<int:projectid>/<int:skillid>/<int:pclass_id>/<int:sel_id>")
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

    return redirect(url_for("convenor.attach_skills", id=projectid, pclass_id=pclass_id, sel_id=sel_id, create=create))


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

    return render_template_context("convenor/attach_programmes.html", data=proj, programmes=q.all(), pclass_id=pclass_id, create=create)


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
        and_(ProjectClass.active == True, or_(ProjectClass.uses_marker == True, ProjectClass.uses_presentations == True))
    ).all()

    pcl_list = []
    pclass_filter_allowed = ["all"]
    for pcl in pclasses:
        pcl: ProjectClass

        # get current configuration record for this project class
        config: ProjectClassConfig = pcl.most_recent_config
        if config is None:
            flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
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
        "convenor/attach_assessors.html",
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
            "convenor.attach_assessors", id=id, pclass_id=pclass_id, url=url_for("convenor.attached", id=pclass_id), text="convenor dashboard"
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
    live_project.assessors = [f for f in library_project.assessors if library_project.is_assessor(f.id)]
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


@convenor.route("/issue_confirm_requests/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def issue_confirm_requests(id):
    # get details for project class
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    year = get_current_year()

    IssueFacultyConfirmRequestForm = IssueFacultyConfirmRequestFormFactory()
    form = IssueFacultyConfirmRequestForm(request.form)

    if form.is_submitted():
        if form.submit_button.data is True:
            now = date.today()
            deadline = form.request_deadline.data.date()

            # if requests already issued, all we need do is adjust the deadline
            if config.requests_issued:
                if deadline < now:
                    deadline = now + timedelta(days=1)

                config.request_deadline = deadline

                try:
                    db.session.commit()
                    flash(
                        'The project confirmation deadline for "{proj}" has been successfully changed '
                        "to {deadline}.".format(proj=config.name, deadline=config.request_deadline.strftime("%a %d %b %Y")),
                        "success",
                    )
                except SQLAlchemyError as e:
                    db.session.rollback()
                    current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                    flash("Could not modify confirmation deadline due to a database error. Please contact a system administrator", "error")

            # otherwise we need to spawn a background task to issue the confirmation requests
            else:
                # schedule an asynchronous task to issue the requests by email

                # get issue task instance
                celery = current_app.extensions["celery"]
                issue = celery.tasks["app.tasks.issue_confirm.pclass_issue"]
                issue_fail = celery.tasks["app.tasks.issue_confirm.issue_fail"]

                # register as a new background task and push it to the scheduler
                task_id = register_task(
                    'Issue project confirmations for "{proj}" {yra}-{yrb}'.format(proj=config.name, yra=year, yrb=year + 1),
                    owner=current_user,
                    description='Issue project confirmations for "{proj}"'.format(proj=config.name),
                )

                if deadline < now:
                    deadline = now + timedelta(weeks=2)

                issue.apply_async(args=(task_id, id, current_user.id, deadline), task_id=task_id, link_error=issue_fail.si(task_id, current_user.id))

        elif hasattr(form, "skip_button") and form.skip_button.data is True:
            now = date.today()

            # mark this configuration has having requests skipped
            config.requests_skipped = True
            config.requests_skipped_timestamp = now
            config.requests_skipped_id = current_user.id

            config.confirmation_required = []

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                flash("Could not perform skip of confirmation requests due to a dataabase error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@convenor.route("/outstanding_confirm/<int:id>")
@roles_accepted("faculty", "admin", "root")
def outstanding_confirm(id):
    # id is a ProjectClassConfig
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    return render_template_context("convenor/dashboard/outstanding_confirm.html", config=config, pclass=config.project_class)


@convenor.route("/outstanding_confirm_ajax/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def outstanding_confirm_ajax(id):
    """
    Ajax data point for waiting-to-go-live faculty list on dashboard
    :param id:
    :return:
    """
    # id is a ProjectClassConfig
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return jsonify({})

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return jsonify({})

    return ajax.convenor.outstanding_confirm_data(
        config, text="list of outstanding confirmations", url=url_for("convenor.outstanding_confirm", id=id)
    )


@convenor.route("/confirmation_reminder/<int:id>")
@roles_accepted("faculty", "admin", "root")
def confirmation_reminder(id):
    # id is a ProjectClassConfig
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS:
        flash("Cannot issue reminder emails for this project class because confirmation requests have not yet been generated", "info")
        return redirect(redirect_url())

    if config.selector_lifecycle > ProjectClassConfig.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS:
        flash("Cannot issue reminder emails for this project class because no further confirmation requests are outstanding", "info")
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    email_task = celery.tasks["app.tasks.issue_confirm.reminder_email"]

    email_task.apply_async((id, current_user.id))

    return redirect(redirect_url())


@convenor.route("/confirmation_reminder_individual/<int:fac_id>/<int:config_id>")
def confirmation_reminder_individual(fac_id, config_id):
    # id is a ProjectClassConfig
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(config_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS:
        flash("Cannot issue reminder emails for this project class because confirmation requests have not yet been generated", "info")
        return redirect(redirect_url())

    if config.selector_lifecycle > ProjectClassConfig.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS:
        flash("Cannot issue reminder emails for this project class because no further confirmation requests are outstanding", "info")
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    email_task = celery.tasks["app.tasks.issue_confirm.send_reminder_email"]
    notify_task = celery.tasks["app.tasks.utilities.email_notification"]

    tk = email_task.si(fac_id, config_id) | notify_task.s(current_user.id, "Reminder email has been sent", "info")
    tk.apply_async()

    return redirect(redirect_url())


@convenor.route("/show_unofferable")
@roles_accepted("faculty", "admin", "root")
def show_unofferable():
    # special-case of unattached projects; reject user if not administrator
    if not validate_is_administrator():
        return redirect(redirect_url())

    return render_template_context("convenor/unofferable.html")


@convenor.route("/unofferable_ajax", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def unofferable_ajax():
    """
    AJAX endpoint for show-unattached view
    :return:
    """

    if not validate_is_administrator():
        return jsonify({})

    base_query = (
        db.session.query(Project)
        .filter(Project.active == True)
        .join(User, User.id == Project.owner_id, isouter=True)
        .filter(or_(Project.generic == True, User.active == True))
    )

    def row_filter(row: Project):
        # don't show offerable projects
        if row.is_offerable:
            return False

        return True

    # in-memory handler is much slower than the SQL handler, but since it does not seem possible to write an
    # SQL query for .is_offerable, we are stuck with it
    return project_list_in_memory_handler(
        request,
        base_query,
        row_filter=row_filter,
        current_user_id=current_user.id,
        menu_template="unofferable",
        name_labels=True,
        text="unofferable projects list",
        url=url_for("convenor.show_unofferable"),
        show_approvals=False,
        show_errors=True,
    )


@convenor.route("/force_confirm_all/<int:id>")
@roles_accepted("faculty", "admin", "root")
def force_confirm_all(id):
    # get details for project class
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    if not config.requests_issued:
        flash(
            "Confirmation requests have not yet been issued for {project} {yeara}-{yearb}".format(
                project=config.name, yeara=config.submit_year_a, yearb=config.submit_year_b
            )
        )
        return redirect(redirect_url())

    if config.live:
        flash(
            "Confirmation is no longer required for {project} {yeara}-{yearb} because this project "
            "has already gone live".format(project=config.name, yeara=config.submit_year_a, yearb=config.submit_year_b)
        )
        return redirect(redirect_url())

    # because we filter on supervisor state, this won't confirm projects from any faculty who are bought-out or
    # on sabbatical
    records = db.session.query(EnrollmentRecord).filter_by(pclass_id=config.pclass_id, supervisor_state=EnrollmentRecord.SUPERVISOR_ENROLLED)

    task_args_list = []
    for rec in records:
        if config.is_confirmation_required(rec.owner_id):
            config.mark_confirmed(rec.owner_id, message=False)

            # if the database commit is successful, we later want to kick off a background task
            # to check whether any other project classes in which this user is enrolled
            # have been reduced to zero confirmations left.
            # If so, treat this 'Confirm' click as accounting for them also
            task_args_list.append((rec.owner_id, config.pclass_id))

    try:
        db.session.commit()
        flash("All outstanding confirmation requests have been removed.", "success")

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            'Could not force confirmations for project class "{pclass}" due to a database error. '
            "Please contact a system administrator".format(pclass=config.name),
            "error",
        )

    else:
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.issue_confirm.propagate_confirm"]

        # kick off background tasks as described above
        for args in task_args_list:
            task.apply_async(args=args)

    return redirect(redirect_url())


@convenor.route("/force_confirm/<int:id>/<int:uid>")
@roles_accepted("faculty", "admin", "root")
def force_confirm(id, uid):
    # get details for project class
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)
    fac: FacultyData = FacultyData.query.get_or_404(uid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    if not config.requests_issued:
        flash(
            "Confirmation requests have not yet been issued for {project} {yeara}-{yearb}".format(
                project=config.name, yeara=config.submit_year_a, yearb=config.submit_year_b
            )
        )
        return redirect(redirect_url())

    if config.live:
        flash(
            "Confirmation is no longer required for {project} {yeara}-{yearb} because this project "
            "has already gone live".format(project=config.name, yeara=config.submit_year_a, yearb=config.submit_year_b)
        )
        return redirect(redirect_url())

    try:
        if config.is_confirmation_required(uid):
            config.mark_confirmed(fac, message=False)
            db.session.commit()

        # kick off a background task to check whether any other project classes in which this user is enrolled
        # have been reduced to zero confirmations left.
        # If so, treat this 'Confirm' click as accounting for them also
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.issue_confirm.propagate_confirm"]
        task.apply_async(args=(uid, config.pclass_id))

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            'Could not force confirmations for user "{user}" and project class "{pclass}" due to a database error. '
            "Please contact a system administrator".format(user=fac.user.name, pclass=config.name),
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/confirm_description/<int:config_id>/<int:did>")
@roles_accepted("faculty", "admin", "root")
def confirm_description(config_id, did):
    # get details for project class
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(config_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    if not config.requests_issued:
        flash(
            "Confirmation requests have not yet been issued for {project} {yeara}-{yearb}".format(
                project=config.name, yeara=config.submit_year_a, yearb=config.submit_year_b
            ),
            "info",
        )
        return redirect(redirect_url())

    if config.live:
        flash(
            "Confirmation is no longer required for {project} {yeara}-{yearb} because this project "
            "has already gone live".format(project=config.name, yeara=config.submit_year_a, yearb=config.submit_year_b),
            "info",
        )
        return redirect(redirect_url())

    desc: ProjectDescription = ProjectDescription.query.get_or_404(did)

    # reject user if can't edit this description
    if not validate_edit_description(desc):
        return redirect(redirect_url())

    # reject if a generic project
    if desc.parent.generic:
        flash("Individual faculty members cannot confirm generic projects.", "info")

    try:
        desc.confirmed = True
        db.session.flush()

        # if no further confirmations outstanding, mark whole configuration as confirmed
        if desc.parent is not None and desc.parent.owner is not None:
            if not config.has_confirmations_outstanding(desc.parent.owner):
                config.mark_confirmed(desc.parent.owner, message=False)

        db.session.commit()

        # kick off a background task to check whether any other project classes in which this user is enrolled
        # have been reduced to zero confirmations left.
        # If so, treat this 'Confirm' click as accounting for them also
        if desc.parent.owner is not None:
            celery = current_app.extensions["celery"]
            task = celery.tasks["app.tasks.issue_confirm.propagate_confirm"]
            task.apply_async(args=(desc.parent.owner.id, config.pclass_id))

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            'Could not confirm description "{desc}" for project "{proj}" due to a database error. '
            "Please contact a system administrator".format(desc=desc.label, proj=desc.parent.name),
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/go_live/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def go_live(id):
    # get details for current pclass configuration
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    if config.live:
        flash('A request to Go Live was ignored, because project "{name}" is already ' "live.".format(name=config.project_class.name), "error")
        return request.referrer

    GoLiveForm = GoLiveFormFactory()
    form: GoLiveForm = GoLiveForm(request.form)

    if form.is_submitted():
        # schedule an asynchronous go-live task
        deadline = form.live_deadline.data

        # are we going to close immediately after?
        if hasattr(form, "live_and_close"):
            close = bool(form.live_and_close.data)
        else:
            close = False

        notify_faculty = bool(form.notify_faculty.data)
        notify_selectors = bool(form.notify_selectors.data)
        accommodate_matching = form.accommodate_matching.data
        full_CATS = form.full_CATS.data

        if deadline is None:
            flash("A request to Go Live was ignored because no deadline was entered.", "error")
        else:
            return redirect(
                url_for(
                    "convenor.confirm_go_live",
                    id=id,
                    close=int(close),
                    deadline=deadline.isoformat(),
                    notify_faculty=int(notify_faculty),
                    notify_selectors=int(notify_selectors),
                    accommodate_matching=accommodate_matching.id if accommodate_matching is not None else None,
                    full_CATS=full_CATS if full_CATS is not None else None,
                )
            )

    return redirect(redirect_url())


def _flash_blocking_tasks(operation: str, blocking):
    flashed_tasks = 0
    max_tasks_to_flash = 5

    for task in blocking["submitter"]:
        task: ConvenorTask

        if flashed_tasks >= max_tasks_to_flash:
            break
        flash('Submitter task "{name}" is blocking {operation}'.format(name=task.name, operation=operation), "warning")
        flashed_tasks += 1

    if flashed_tasks >= max_tasks_to_flash:
        return

    for task in blocking["selector"]:
        task: ConvenorTask
        if flashed_tasks >= max_tasks_to_flash:
            break
        flash('Selector task "{name}" is blocking {operation}'.format(name=task.name, operation=operation), "warning")
        flashed_tasks += 1

    if flashed_tasks >= max_tasks_to_flash:
        return

    for task in blocking["global"]:
        task: ConvenorTask
        if flashed_tasks >= max_tasks_to_flash:
            break
        flash('Global project class task "{name}" is blocking {operation}'.format(name=task.name, operation=operation), "warning")
        flashed_tasks += 1


@convenor.route("/confirm_go_live/<int:id>")
@roles_accepted("faculty", "admin", "root")
def confirm_go_live(id):
    # get details for current pclass configuration
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(url_for("convenor.status", id=config.pclass_id))

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(url_for("convenor.status", id=config.pclass_id))

    if config.live:
        flash('A request to Go Live was ignored, because project "{name}" is already ' "live.".format(name=config.project_class.name), "error")
        return redirect(url_for("convenor.status", id=config.pclass_id))

    blocking, num_blocking = config.get_blocking_tasks
    if num_blocking > 0:
        _flash_blocking_tasks("Go-Live", blocking)
        return redirect(url_for("convenor.status", id=config.pclass_id))

    close = bool(int(request.args.get("close", 0)))
    deadline = request.args.get("deadline", None)
    notify_faculty = bool(int(request.args.get("notify_faculty", 0)))
    notify_selectors = bool(int(request.args.get("notify_selectors", 0)))
    accommodate_matching = request.args.get("accommodate_matching", None)
    full_CATS = request.args.get("full_CATS", None)
    if accommodate_matching is not None:
        accommodate_matching = int(accommodate_matching)
    if full_CATS is not None:
        full_CATS = int(full_CATS)

    if deadline is None:
        flash(
            "A request to Go Live was ignored because the deadline was not correctly received. Please report this issue to an administrator.",
            "error",
        )
        redirect(url_for("convenor.status", id=config.pclass_id))

    deadline = parser.parse(deadline).date()

    year = get_current_year()

    title = 'Go Live for "{name}" {yeara}&ndash;{yearb}'.format(name=config.project_class.name, yeara=year, yearb=year + 1)
    action_url = url_for(
        "convenor.perform_go_live",
        id=id,
        close=int(close),
        notify_faculty=int(notify_faculty),
        notify_selectors=int(notify_selectors),
        deadline=deadline.isoformat(),
        accommodate_matching=accommodate_matching,
        full_CATS=full_CATS,
    )
    message = (
        '<p>Please confirm that you wish to Go Live for project class "{name}" {yeara}&ndash;{yearb}, '
        "with deadline {deadline}.</p>"
        "<p>This action cannot be undone.</p>".format(
            name=config.project_class.name, yeara=year, yearb=year + 1, deadline=deadline.strftime("%a %d %b %Y")
        )
    )
    submit_label = "Go Live"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=title, action_url=action_url, message=message, submit_label=submit_label
    )


@convenor.route("/perform_go_live/<int:id>")
@roles_accepted("faculty", "admin", "root")
def perform_go_live(id):
    # get details for current pclass configuration
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    if config.live:
        flash('A request to Go Live was ignored, because project "{name}" is already ' "live.".format(name=config.project_class.name), "error")
        return redirect(redirect_url())

    blocking, num_blocking = config.get_blocking_tasks
    if num_blocking > 0:
        _flash_blocking_tasks("Go-Live", blocking)
        return redirect(redirect_url())

    close = bool(int(request.args.get("close", 0)))
    deadline = request.args.get("deadline", None)
    notify_faculty = bool(int(request.args.get("notify_faculty", 0)))
    notify_selectors = bool(int(request.args.get("notify_selectors", 0)))
    accommodate_matching = request.args.get("accommodate_matching", None)
    full_CATS = request.args.get("full_CATS", None)
    if accommodate_matching is not None:
        accommodate_matching = int(accommodate_matching)
    if full_CATS is not None:
        full_CATS = int(full_CATS)

    if deadline is None:
        flash("A request to Go Live was ignored because the deadline was not correctly received", "error")
        return redirect(redirect_url())

    deadline = parser.parse(deadline).date()

    year = get_current_year()

    celery = current_app.extensions["celery"]
    golive = celery.tasks["app.tasks.go_live.pclass_golive"]
    golive_fail = celery.tasks["app.tasks.go_live.golive_fail"]
    golive_close = celery.tasks["app.tasks.go_live.golive_close"]

    # register Go Live as a new background task and push it to the celery scheduler
    task_id = register_task(
        'Go Live for "{proj}" {yra}-{yrb}'.format(proj=config.name, yra=year, yrb=year + 1),
        owner=current_user,
        description='Perform Go Live of "{proj}"'.format(proj=config.name),
    )

    if close:
        seq = chain(
            golive.si(task_id, id, current_user.id, deadline, True, notify_faculty, notify_selectors, accommodate_matching, full_CATS),
            golive_close.si(id, current_user.id),
        ).on_error(golive_fail.si(task_id, current_user.id))
        seq.apply_async()

    else:
        golive.apply_async(
            args=(task_id, id, current_user.id, deadline, False, notify_faculty, notify_selectors, accommodate_matching, full_CATS),
            task_id=task_id,
            link_error=golive_fail.si(task_id, current_user.id),
        )

    return redirect(url_for("convenor.status", id=config.pclass_id))


@convenor.route("/reverse_golive/<int:config_id>")
@roles_accepted("faculty", "admin", "root")
def reverse_golive(config_id):
    # config id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(config_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    config.live = False
    config.live_deadline = None

    db.session.commit()

    return redirect(url_for("convenor.status", id=config.pclass_id))


@convenor.route("/adjust_selection_deadline/<int:configid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def adjust_selection_deadline(configid):
    # config id is a ProjectClassConfig
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(configid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    # reject if project class is not live
    if not config.live:
        flash(
            'A request to adjust the selection deadline for "{proj}" was ignored, because '
            "this project class is not yet live.".format(proj=config.name),
            "error",
        )
        return redirect(redirect_url())

    if config.live_deadline is None:
        flash(
            'A request to adjust the selection deadline for "{proj}" was ignored, because '
            "the deadline has not yet been set for this project class.".format(proj=config.name),
            "error",
        )
        return redirect(redirect_url())

    ChangeDeadlineForm = ChangeDeadlineFormFactory()
    form = ChangeDeadlineForm(request.form)

    if form.validate_on_submit():
        if form.change.data:
            config.live_deadline = form.live_deadline.data

            try:
                db.session.commit()
                flash(
                    'The deadline for student selections for "{proj}" has been successfully changed '
                    "to {deadline}.".format(proj=config.name, deadline=config.live_deadline.strftime("%a %d %b %Y")),
                    "success",
                )
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                flash(
                    'Could not adjust selection deadline for "{proj}" due to database error. '
                    "Please contact a system administrator".format(proj=config.name),
                    "error",
                )

        elif form.close.data:
            notify_convenor = form.notify_convenor.data

            year = get_current_year()

            celery = current_app.extensions["celery"]
            close = celery.tasks["app.tasks.close_selection.pclass_close"]
            close_fail = celery.tasks["app.tasks.close_selection.close_fail"]

            # register as new background task and push to celery scheduler
            task_id = register_task(
                'Close selections for "{proj}" {yra}-{yrb}'.format(proj=config.name, yra=year, yrb=year + 1),
                owner=current_user,
                description='Close selections for "{proj}"'.format(proj=config.name),
            )

            close.apply_async(
                args=(task_id, config.id, current_user.id, notify_convenor), task_id=task_id, link_error=close_fail.si(task_id, current_user.id)
            )

            # pclass_close task posts a user message if the close logic proceeds correctly.

    return redirect(url_for("convenor.status", id=config.pclass_id))


@convenor.route("/submit_student_selection/<int:sel_id>")
@roles_accepted("faculty", "admin", "root")
def submit_student_selection(sel_id):
    # sel_id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sel_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    valid, errors = sel.is_valid_selection
    if not valid:
        flash(
            "The current bookmark list is not a valid set of project preferences. This is an internal error; "
            "please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    try:
        store_selection(sel)

        db.session.commit()

        celery = current_app.extensions["celery"]
        send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]

        msg = EmailMultiAlternatives(
            subject="An administrator has submitted project choices on your behalf ({pcl})".format(pcl=sel.config.project_class.name),
            from_email=current_app.config["MAIL_DEFAULT_SENDER"],
            reply_to=[current_user.email],
            to=[sel.student.user.email, current_user.email],
        )

        msg.body = render_template_context(
            "email/student_notifications/choices_received_proxy.txt",
            user=sel.student.user,
            pclass=sel.config.project_class,
            config=sel.config,
            sel=sel,
        )

        # register a new task in the database
        task_id = register_task(msg.subject, description="Send project choices confirmation email to {r}".format(r=", ".join(msg.to)))
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        flash(
            "Project choices for this selector have been successfully stored. "
            "A confirmation email has been sent to the selector's registered email address "
            "and cc'd to you.",
            "info",
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        flash("A database error occurred during submission. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/force_submit_selection/<int:sel_id>")
@roles_accepted("admin", "root")
def force_submit_selection(sel_id):
    # sel_id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sel_id)

    if not sel.has_bookmarks:
        flash('Selector "{name}" cannot be force-submit because they do not have ' "bookmarks.".format(name=sel.student.user.name), "info")
        return redirect(redirect_url())

    store_selection(sel)

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("A database error occurred during forced submission. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/enroll/<int:userid>/<int:pclassid>")
@roles_accepted("faculty", "admin", "root")
def enroll(userid, pclassid):
    # get details for project class
    pclass = ProjectClass.query.get_or_404(pclassid)

    # reject user if not a suitable convenor or administrator
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(pclass):
        return redirect(redirect_url())

    data = FacultyData.query.get_or_404(userid)
    data.add_enrollment(pclass)

    return redirect(redirect_url())


@convenor.route("/unenroll/<int:userid>/<int:pclassid>")
@roles_accepted("faculty", "admin", "root")
def unenroll(userid, pclassid):
    # get details for project class
    pclass = ProjectClass.query.get_or_404(pclassid)

    # reject user if not a suitable convenor or administrator
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(pclass):
        return redirect(redirect_url())

    data = FacultyData.query.get_or_404(userid)
    data.remove_enrollment(pclass)

    return redirect(redirect_url())


@convenor.route("/confirm/<int:sid>/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def confirm(sid, pid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(redirect_url())

    if do_confirm(sel, project):
        db.session.commit()

    return redirect(redirect_url())


@convenor.route("/deconfirm/<int:sid>/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def deconfirm(sid, pid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(redirect_url())

    if do_deconfirm(sel, project):
        db.session.commit()

    return redirect(redirect_url())


@convenor.route("/deconfirm_to_pending/<int:sid>/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def deconfirm_to_pending(sid, pid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(redirect_url())

    if do_deconfirm_to_pending(sel, project):
        db.session.commit()

    return redirect(redirect_url())


@convenor.route("/cancel_confirm/<int:sid>/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def cancel_confirm(sid, pid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(redirect_url())

    if do_cancel_confirm(sel, project):
        db.session.commit()

    return redirect(redirect_url())


@convenor.route("/project_confirm_all/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def project_confirm_all(pid):
    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not validate_is_convenor(pclass):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(project.config):
        return redirect(redirect_url())

    waiting = project.requests_waiting
    for req in waiting:
        req.confirm()

    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/project_clear_requests/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def project_clear_requests(pid):
    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not validate_is_convenor(pclass):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(project.config):
        return redirect(redirect_url())

    waiting = project.requests_waiting
    for req in waiting:
        req.remove()
        db.session.delete(req)

    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/project_remove_confirms/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def project_remove_confirms(pid):
    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not validate_is_convenor(pclass):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(project.config):
        return redirect(redirect_url())

    confirmed = project.requests_confirmed
    for req in confirmed:
        req.remove()
        db.session.delete(req)

    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/project_make_all_confirms_pending/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def project_make_all_confirms_pending(pid):
    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not validate_is_convenor(pclass):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(project.config):
        return redirect(redirect_url())

    confirmed = project.requests_confirmed
    for req in confirmed:
        req.waiting()

    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/student_confirm_all/<int:sid>")
@roles_accepted("faculty", "admin", "root")
def student_confirm_all(sid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(redirect_url())

    waiting = sel.requests_waiting
    for req in waiting:
        req.confirm()

    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/student_remove_confirms/<int:sid>")
@roles_accepted("faculty", "admin", "root")
def student_remove_confirms(sid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(redirect_url())

    confirmed = sel.requests_confirmed
    for req in confirmed:
        req.remove()
        db.session.delete(req)

    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/student_clear_requests/<int:sid>")
@roles_accepted("faculty", "admin", "root")
def student_clear_requests(sid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(redirect_url())

    waiting = sel.requests_waiting
    for req in waiting:
        req.remove()
        db.session.delete(req)

    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/student_make_all_confirms_pending/<int:sid>")
@roles_accepted("faculty", "admin", "root")
def student_make_all_confirms_pending(sid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(redirect_url())

    confirmed = sel.requests_confirmed
    for req in confirmed:
        req.waiting()

    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/enable_conversion/<int:sid>")
@roles_accepted("faculty", "admin", "root")
def enable_conversion(sid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    sel.convert_to_submitter = True
    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/disable_conversion/<int:sid>")
@roles_accepted("faculty", "admin", "root")
def disable_conversion(sid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    sel.convert_to_submitter = False
    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/email_selectors/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def email_selectors(configid):
    # configid is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(configid)

    # validate that logged-in user is a convenor for this project type
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    convert_filter = request.args.get("convert_filter")
    year_filter = request.args.get("year_filter")
    match_filter = request.args.get("match_filter")
    match_show = request.args.get("match_show")

    data = _build_selector_data(config, cohort_filter, prog_filter, state_filter, convert_filter, year_filter, match_filter, match_show)

    if len(data) > 0:
        to_list = []
        for s in data:
            to_list.append(s.student_id)

    else:
        to_list = None

    return redirect(
        url_for(
            "services.send_email",
            url=url_for(
                "convenor.selectors",
                id=config.pclass_id,
                cohort_filter=cohort_filter,
                prog_filter=prog_filter,
                state_filter=state_filter,
                year_filter=year_filter,
                match_filter=match_filter,
                match_show=match_show,
            ),
            text="selectors view",
            to=to_list,
        )
    )


@convenor.route("/email_submitters/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def email_submitters(configid):
    # configid is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(configid)

    # validate that logged-in user is a convenor for this project type
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    year_filter = request.args.get("year_filter")
    data_display = request.args.get("data_display")

    data = build_submitters_data(config, cohort_filter, prog_filter, state_filter, year_filter)

    if len(data) > 0:
        to_list = []
        for s in data:
            to_list.append(s.student_id)

    else:
        to_list = None

    return redirect(
        url_for(
            "services.send_email",
            url=url_for(
                "convenor.submitters",
                id=config.pclass_id,
                cohort_filter=cohort_filter,
                prog_filter=prog_filter,
                state_filter=state_filter,
                year_filter=year_filter,
                data_display=data_display,
            ),
            text="submitters view",
            to=to_list,
        )
    )


@convenor.route("/convert_all/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def convert_all(configid):
    # configid is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(configid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_is_convenor(config.project_class):
        return home_dashboard()

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    convert_filter = request.args.get("convert_filter")
    year_filter = request.args.get("year_filter")
    match_filter = request.args.get("match_filter")
    match_show = request.args.get("match_show")

    data = _build_selector_data(config, cohort_filter, prog_filter, state_filter, convert_filter, year_filter, match_filter, match_show)

    for s in data:
        s.convert_to_submitter = True

    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/convert_none/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def convert_none(configid):
    # sid is a SelectingStudent
    config = ProjectClassConfig.query.get_or_404(configid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_is_convenor(config.project_class):
        return home_dashboard()

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    convert_filter = request.args.get("convert_filter")
    year_filter = request.args.get("year_filter")
    match_filter = request.args.get("match_filter")
    match_show = request.args.get("match_show")

    data = _build_selector_data(config, cohort_filter, prog_filter, state_filter, convert_filter, year_filter, match_filter, match_show)

    for s in data:
        s.convert_to_submitter = False

    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/student_clear_bookmarks/<int:sid>")
@roles_accepted("faculty", "admin", "root")
def student_clear_bookmarks(sid):
    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(redirect_url())

    for item in sel.bookmarks:
        db.session.delete(item)

    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/confirm_rollover/<int:id>")
@roles_accepted("faculty", "admin", "root")
def confirm_rollover(id):
    # pid is a ProjectClass
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # should marker information be populated (if it is available)?
    use_markers = bool(int(request.args.get("markers", 0)))

    year = get_current_year()
    if config.year == year:
        flash("This project is not yet ready to rollover.", "info")
        return redirect(redirect_url())

    if not config.project_class.active:
        flash("{name} is not an active project class, and therefore cannot be rolled over.".format(name=config.name), "error")
        return redirect(redirect_url())

    blocking, num_blocking = config.get_blocking_tasks
    if num_blocking > 0:
        _flash_blocking_tasks("roll-over to next academic year", blocking)
        return redirect(redirect_url())

    title = 'Rollover of "{proj}" to {yeara}&ndash;{yearb}'.format(proj=config.name, yeara=year, yearb=year + 1)
    action_url = url_for("convenor.rollover", id=id, url=request.referrer, markers=int(use_markers))
    message = (
        '<p>Please confirm that you wish to rollover project class "{proj}" to '
        "{yeara}&ndash;{yearb}.</p>"
        "<p>This action cannot be undone.</p>".format(proj=config.name, yeara=year, yearb=year + 1)
    )

    if config.select_in_previous_cycle:
        if use_markers:
            submit_label = "Rollover to {yr}".format(yr=year)
        else:
            submit_label = "Rollover to {yr} and drop markers".format(yr=year)
    else:
        submit_label = "Rollover to {yr}".format(yr=year)

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=title, action_url=action_url, message=message, submit_label=submit_label
    )


@convenor.route("/rollover/<int:id>")
@roles_accepted("faculty", "admin", "root")
def rollover(id):
    # pid is a ProjectClass
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)

    url = request.args.get("url", None)
    use_markers = bool(int(request.args.get("markers", 0)))

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(url) if url is not None else home_dashboard()

    year = get_current_year()
    if config.year == year:
        flash(
            f'A rollover request was ignored for project class "{config.name}" because its '
            f"configuration already matches the current academic year. "
            f"If you are attempting to rollover the academic year and believe that you "
            f"have not managed to do so, please contact a system administrator.",
            "error",
        )
        return redirect(url) if url is not None else home_dashboard()

    if not config.project_class.active:
        flash(f'"{config.name}" is not an active project class, and cannot be rolled over.', "error")
        return redirect(url) if url is not None else home_dashboard()

    blocking, num_blocking = config.get_blocking_tasks
    if num_blocking > 0:
        _flash_blocking_tasks("roll-over to next academic year", blocking)
        return redirect(url) if url is not None else home_dashboard()

    # build task chains
    celery = current_app.extensions["celery"]
    rollover = celery.tasks["app.tasks.rollover.pclass_rollover"]
    backup_msg = celery.tasks["app.tasks.rollover.rollover_backup_msg"]
    backup = celery.tasks["app.tasks.backup.backup"]
    rollover_fail = celery.tasks["app.tasks.rollover.rollover_fail"]

    # originally, everything was put into a single chain. But (for reasons that are not yet clear)
    # this just led to an indefinite hang, perhaps similar to the issue reported here:
    # https://stackoverflow.com/questions/53507677/group-of-chains-hanging-forever-in-celery

    # So, instead, we effectively implement our own version of the chain logic.

    # register rollover as a new background task and push it to the celery scheduler
    task_id = register_task(
        'Rollover "{proj}" to {yra}-{yrb}'.format(proj=config.name, yra=year, yrb=year + 1),
        owner=current_user,
        description='Perform rollover of "{proj}" to new academic year'.format(proj=config.name),
    )

    backup_chain = chain(
        backup_msg.si(task_id),
        backup.si(
            current_user.id,
            type=BackupRecord.PROJECT_ROLLOVER_FALLBACK,
            tag="rollover",
            description="Rollback snapshot for {proj} rollover to {yr}".format(proj=config.name, yr=year),
        ),
    )
    backup_result = backup_chain.apply_async()
    backup_result.wait(timeout=None, interval=0.5)

    # TODO: should prefer to set up a chain, and then return from the WSGI process so that we can
    #  free up the web server thread. Not quite sure why this wasn't done, but maybe issues with chords?
    #  We have seen that elsewhere with Celery.
    if not backup_result.successful():
        flash(
            f'Could not complete rollover for project class "{config.name}" because the preparatory '
            f"backup task did not complete. Please contact a system administrator.",
            "error",
        )
        return redirect(url) if url is not None else home_dashboard()

    rollover_result: AsyncResult = rollover.apply_async(
        args=(task_id, use_markers, id, current_user.id), task_id=task_id, link_error=rollover_fail.si(task_id, current_user.id)
    )

    return redirect(url) if url is not None else home_dashboard()


@convenor.route("/reset_popularity_data/<int:id>")
@roles_accepted("faculty", "admin", "root")
def reset_popularity_data(id):
    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    title = "Delete popularity data"
    panel_title = "Delete selection popularity data for <strong>{name} {yra}&ndash;{yrb}</strong>".format(
        name=config.name, yra=config.select_year_a, yrb=config.select_year_b
    )

    action_url = url_for("convenor.perform_reset_popularity_data", id=id)
    message = (
        "<p>Please confirm that you wish to delete all popularity data for "
        "<strong>{name} {yra}&ndash;{yrb}</strong>.</p>"
        "<p>This action cannot be undone.</p>"
        "<p>Afterwards, it will not be possible to analyse "
        "historical popularity trends for individual projects offered in this cycle.</p>".format(
            name=config.name, yra=config.select_year_a, yrb=config.select_year_b
        )
    )
    submit_label = "Delete data"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@convenor.route("/perform_reset_popularity_data/<int:id>")
@roles_accepted("faculty", "admin", "root")
def perform_reset_popularity_data(id):
    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    db.session.query(PopularityRecord).filter_by(config_id=id).delete()
    db.session.commit()

    return redirect(url_for("convenor.liveprojects", id=config.pclass_id))


@convenor.route("/selector_bookmarks/<int:id>")
@roles_accepted("faculty", "admin", "root")
def selector_bookmarks(id):
    # id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to view selector rankings before the corresponding project class has gone live.", "error")
        return redirect(redirect_url())

    return render_template_context("convenor/selector/student_bookmarks.html", sel=sel)


@convenor.route("/project_bookmarks/<int:id>")
@roles_accepted("faculty", "admin", "root")
def project_bookmarks(id):
    # id is a LiveProject
    proj: LiveProject = LiveProject.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return redirect(redirect_url())

    state = proj.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to view selector rankings before the corresponding project class has gone live.", "error")
        return redirect(redirect_url())

    return render_template_context("convenor/selector/project_bookmarks.html", project=proj)


def _demap_project(item_id):
    result = parse.parse("P-{pid}", item_id)

    return int(result["pid"])


@convenor.route("/update_student_bookmarks", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def update_student_bookmarks():
    data = request.get_json()

    # discard if request is ill-formed
    if "ranking" not in data or "sid" not in data:
        return jsonify({"status": "ill_formed"})

    ranking = data["ranking"]
    sid = data["sid"]

    # sid is a SelectingStudent
    sel: SelectingStudent = db.session.query(SelectingStudent).filter_by(id=sid).first()

    if sel is None:
        return jsonify({"status": "data_missing"})

    if sel.retired:
        return jsonify({"status": "not_live"})

    if not validate_is_convenor(sel.config.project_class, message=False):
        return jsonify({"status": "insufficient_privileges"})

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        return jsonify({"status": "too_early"})

    projects = map(_demap_project, ranking)

    rmap = {}
    index = 1
    for p in projects:
        rmap[p] = index
        index += 1

    # update ranking
    for bookmark in sel.bookmarks:
        bookmark: Bookmark
        bookmark.rank = rmap[bookmark.liveproject.id]

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return jsonify({"status": "database_failure"})

    return jsonify({"status": "success"})


@convenor.route("/delete_student_bookmark/<int:sid>/<int:bid>")
@roles_accepted("faculty", "admin", "root")
def delete_student_bookmark(sid, bid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # bid is a Bookmark
    bookmark: Bookmark = Bookmark.query.get_or_404(bid)

    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to delete selector bookmarks before the corresponding project class has gone live.", "error")
        return redirect(redirect_url())

    title = "Delete selector bookmark"
    panel_title = (
        'Delete bookmark for selector <i class="fas fa-user-circle"></i> <strong>{name}</strong>, '
        "project <strong>{proj}</strong>".format(name=sel.student.user.name, proj=bookmark.liveproject.name)
    )
    action_url = url_for("convenor.perform_delete_student_bookmark", sid=sid, bid=bid)
    message = (
        '<p>Please confirm that you wish to delete <i class="fas fa-user-circle"></i> <strong>{name}</strong> '
        "bookmark for project <strong>{proj}</strong>.</p>"
        "<p>This action cannot be undone.</p>".format(name=sel.student.user.name, proj=bookmark.liveproject.name)
    )
    submit_label = "Delete bookmark"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@convenor.route("/perform_delete_student_bookmark/<int:sid>/<int:bid>")
@roles_accepted("faculty", "admin", "root")
def perform_delete_student_bookmark(sid, bid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to delete selector bookmarks before the corresponding project class has gone live.", "error")
        return redirect(url_for("convenor.selector_bookmarks", id=sid))

    bm: Bookmark = sel.bookmarks.filter_by(id=bid).first()

    if bm:
        sel.bookmarks.remove(bm)
        sel.re_rank_bookmarks()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash("Could not remove bookmark due to a database error. Please inform a system administrator.", "info")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            db.session.rollback()

    return redirect(url_for("convenor.selector_bookmarks", id=sid))


@convenor.route("/add_student_bookmark/<int:sid>")
@roles_accepted("faculty", "admin", "office")
def add_student_bookmark(sid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to add a selector bookmark before the corresponding project class has gone live.", "error")
        return redirect(redirect_url())

    return render_template_context("convenor/selector/add_bookmark.html", sel=sel)


@convenor.route("/add_student_bookmark_ajax/<int:sid>")
@roles_accepted("faculty", "admin", "office")
def add_student_bookmark_ajax(sid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return jsonify({})

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to add a selector bookmark before the corresponding project class has gone live.", "error")
        return jsonify({})

    config = sel.config
    projects = config.live_projects.filter(~LiveProject.bookmarks.any(owner_id=sid))

    return ajax.convenor.add_student_bookmark(projects.all(), sel)


@convenor.route("/create_student_bookmark/<int:sel_id>/<int:proj_id>")
@roles_accepted("faculty", "admin", "root")
def create_student_bookmark(sel_id, proj_id):
    # proj_id is a LiveProject
    proj: LiveProject = LiveProject.query.get_or_404(proj_id)

    # sel_id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sel_id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.selector_bookmarks", id=sel_id)

    # check project and selector belong to the same project class
    if proj.config_id != sel.config_id:
        flash(
            'Project "{pname}" and selector "{sname}" do not belong to the same project class, so a '
            "bookmark cannot be created for this pair.".format(pname=proj.name, sname=sel.student.user.name),
            "error",
        )
        return redirect(url)

    # check whether a bookmark with this project already exists
    q = sel.bookmarks.filter_by(liveproject_id=proj_id)

    if get_count(q) > 0:
        flash(
            'A request to create a bookmark for project "{pname}" and selector "{sname}" was ignored, '
            "because a bookmark for this pair already exists".format(pname=proj.name, sname=sel.student.user.name),
            "info",
        )
        return redirect(url)

    bm = Bookmark(liveproject_id=proj.id, owner_id=sel.id, rank=sel.number_bookmarks + 1)

    try:
        db.session.add(bm)
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not create bookmark due to a database error. Please contact a system administrator", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(url)


@convenor.route("/selector_choices/<int:id>")
@roles_accepted("faculty", "admin", "root")
def selector_choices(id):
    # id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)

    if text is None and url is None:
        url = url_for("convenor.selectors", id=sel.config.pclass_id)
        text = "dashboard"

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to view selector rankings before the corresponding project class has gone live.", "error")
        return redirect(redirect_url())

    if not sel.has_submitted:
        flash(
            "The ranking list for {name} can not yet be inspected because this selector has "
            "not yet submitted their ranked project choices (or accepted a "
            "custom offer.".format(name=sel.student.user.name),
            "info",
        )
        return redirect(redirect_url())

    return render_template_context("convenor/selector/student_choices.html", sel=sel, text=text, url=url)


@convenor.route("/project_choices/<int:id>")
@roles_accepted("faculty", "admin", "root")
def project_choices(id):
    # id is a LiveProject
    proj: LiveProject = LiveProject.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return redirect(redirect_url())

    state = proj.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to view project rankings before the corresponding project class has gone live.", "error")
        return redirect(redirect_url())

    return render_template_context("convenor/selector/project_choices.html", project=proj)


@convenor.route("/update_student_choices", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def update_student_choices():
    data = request.get_json()

    # discard is request is ill-formed
    if "ranking" not in data or "sid" not in data:
        return jsonify({"status": "ill_formed"})

    ranking = data["ranking"]
    sid = data["sid"]

    if ranking is None or sid is None:
        return jsonify({"status": "ill_formed"})

    # sid is a SelectingStudent
    sel: SelectingStudent = db.session.query(SelectingStudent).filter_by(id=sid).first()

    if sel is None:
        return jsonify({"status": "data_missing"})

    if sel.retired:
        return jsonify({"status": "not_live"})

    if not validate_is_convenor(sel.config.project_class, message=False):
        return jsonify({"status": "insufficient_privileges"})

    projects = map(_demap_project, ranking)

    rmap = {}
    index = 1
    for p in projects:
        rmap[p] = index
        index += 1

    # update ranking
    for selection in sel.selections:
        selection.rank = rmap[selection.liveproject.id]

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        return jsonify({"status": "database_failure"})

    return jsonify({"status": "success"})


@convenor.route("/delete_student_choice/<int:sid>/<int:cid>")
@roles_accepted("faculty", "admin", "root")
def delete_student_choice(sid, cid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # cid is a SelectionRecord
    record: SelectionRecord = SelectionRecord.query.get_or_404(cid)

    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to delete selector rankings before the corresponding project class has gone live.", "error")
        return redirect(redirect_url())

    title = "Delete selector ranking"
    panel_title = 'Delete ranking for selector <i class="fas fa-user-circle"></i> <strong>{name}</strong>, ' "project <strong>{proj}</strong>".format(
        name=sel.student.user.name, proj=record.liveproject.name
    )
    action_url = url_for("convenor.perform_delete_student_choice", sid=sid, cid=cid)
    message = (
        '<p>Please confirm that you wish to delete <i class="fas fa-user-circle"></i> <strong>{name}</strong> '
        "ranking #{num} for project <strong>{proj}</strong>.</p>"
        "<p>This action cannot be undone.</p>"
        "<p><strong>Student-submitted rankings should be deleted only when there "
        "is a clear rationale for doing "
        "so.</strong></p>".format(name=sel.student.user.name, num=record.rank, proj=record.liveproject.name)
    )
    submit_label = "Delete ranking"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@convenor.route("/perform_delete_student_choice/<int:sid>/<int:cid>")
@roles_accepted("faculty", "admin", "root")
def perform_delete_student_choice(sid, cid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to delete selector rankings before the corresponding project class has gone live.", "error")
        return redirect(url_for("convenor.selector_bookmarks", id=sid))

    rec: SelectionRecord = sel.selections.filter_by(id=cid).first()

    if rec:
        sel.selections.remove(rec)
        sel.re_rank_selections()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash("Could not remove ranking due to a database error. Please inform a system administrator.", "info")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            db.session.rollback()

    return redirect(url_for("convenor.selector_choices", id=sid))


@convenor.route("/add_student_ranking/<int:sid>")
@roles_accepted("faculty", "admin", "office")
def add_student_ranking(sid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to add a selector ranking before the corresponding project class has gone live.", "error")
        return redirect(redirect_url())

    if not sel.has_submitted:
        flash("It is not possible to add a new ranking until the selector has submitted their own ranked list.", "info")
        return redirect(redirect_url())

    return render_template_context("convenor/selector/add_ranking.html", sel=sel)


@convenor.route("/add_student_ranking_ajax/<int:sid>")
@roles_accepted("faculty", "admin", "office")
def add_student_ranking_ajax(sid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return jsonify({})

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        return jsonify({})

    if not sel.has_submitted:
        return jsonify({})

    config = sel.config
    projects = config.live_projects.filter(~LiveProject.selections.any(owner_id=sid))

    return ajax.convenor.add_student_ranking(projects.all(), sel)


@convenor.route("/create_student_ranking/<int:sel_id>/<int:proj_id>")
@roles_accepted("faculty", "admin", "root")
def create_student_ranking(sel_id, proj_id):
    # proj_id is a LiveProject
    proj: LiveProject = LiveProject.query.get_or_404(proj_id)

    # sel_id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sel_id)

    if not sel.has_submitted:
        flash("It is not possible to add a new ranking until the selector has submitted their own ranked list.", "info")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.selector_bookmarks", id=sel_id)

    # check project and selector belong to the same project class
    if proj.config_id != sel.config_id:
        flash(
            'Project "{pname}" and selector "{sname}" do not belong to the same project class, so a '
            "ranking cannot be created for this pair.".format(pname=proj.name, sname=sel.student.user.name),
            "error",
        )
        return redirect(url)

    # check whether a bookmark with this project already exists
    q = sel.selections.filter_by(liveproject_id=proj_id)

    if get_count(q) > 0:
        flash(
            'A request to create a ranking for project "{pname}" and selector "{sname}" was ignored, '
            "because a ranking for this pair already exists".format(pname=proj.name, sname=sel.student.user.name),
            "info",
        )
        return redirect(url)

    rec = SelectionRecord(
        liveproject_id=proj.id,
        owner_id=sel.id,
        rank=sel.number_selections + 1,
        converted_from_bookmark=False,
        hint=SelectionRecord.SELECTION_HINT_NEUTRAL,
    )

    try:
        db.session.add(rec)
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not create ranking due to a database error. Please contact a system administrator", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(url)


@convenor.route("/selector_confirmations/<int:id>")
@roles_accepted("faculty", "admin", "root")
def selector_confirmations(id):
    # id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to view selector confirmations before the corresponding project class has gone live.", "error")
        return redirect(redirect_url())

    return render_template_context("convenor/selector/student_confirmations.html", sel=sel, now=datetime.now())


@convenor.route("/project_custom_offers/<int:proj_id>")
@roles_accepted("faculty", "admin", "root")
def project_custom_offers(proj_id):
    # proj_id is a LiveProject
    proj: LiveProject = LiveProject.query.get_or_404(proj_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return redirect(redirect_url())

    state = proj.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to view project custom offers before the corresponding project class has gone live.", "error")
        return redirect(redirect_url())

    return render_template_context("convenor/selector/project_custom_offers.html", project=proj, pclass_id=proj.config.project_class.id)


@convenor.route("/project_custom_offers_ajax/<int:proj_id>")
@roles_accepted("faculty", "admin", "root")
def project_custom_offers_ajax(proj_id):
    # proj_id is a LiveProject
    proj: LiveProject = LiveProject.query.get_or_404(proj_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return jsonify({})

    state = proj.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        return jsonify({})

    return ajax.convenor.project_offer_data(proj.ordered_custom_offers.all())


@convenor.route("/selector_custom_offers/<int:sel_id>")
@roles_accepted("faculty", "admin", "root")
def selector_custom_offers(sel_id):
    # sel_id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sel_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to view selector custom offers before the corresponding project class has gone live.", "error")
        return redirect(redirect_url())

    return render_template_context("convenor/selector/student_custom_offers.html", sel=sel, pclass_id=sel.config.project_class.id)


@convenor.route("/selector_custom_offers_ajax/<int:sel_id>")
@roles_accepted("faculty", "admin", "root")
def selector_custom_offers_ajax(sel_id):
    # sel_id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sel_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return jsonify({})

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        return jsonify({})

    return ajax.convenor.student_offer_data(sel.ordered_custom_offers.all())


@convenor.route("/new_selector_offer/<int:sel_id>")
@roles_accepted("faculty", "admin", "root")
def new_selector_offer(sel_id):
    # sel_id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sel_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to set up a new selector custom offer before the corresponding project class has gone live.", "error")
        return redirect(redirect_url())

    return render_template_context("convenor/selector/student_new_offer.html", sel=sel, pclass_id=sel.config.project_class.id)


@convenor.route("/new_selector_offer_ajax/<int:sel_id>")
@roles_accepted("faculty", "admin", "root")
def new_selector_offer_ajax(sel_id):
    # sel_id is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sel_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(sel.config.project_class):
        return jsonify({})

    state = sel.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        return jsonify({})

    config = sel.config
    projects = config.live_projects.filter(~LiveProject.custom_offers.any(selector_id=sel_id))

    return ajax.convenor.student_offer_projects(projects.all(), sel)


@convenor.route("/new_project_offer/<int:proj_id>")
@roles_accepted("faculty", "admin", "root")
def new_project_offer(proj_id):
    # proj_id is a LiveProject
    proj = LiveProject.query.get_or_404(proj_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return redirect(redirect_url())

    state = proj.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to set up a new custom offer before the corresponding project class has gone live.", "error")
        return redirect(redirect_url())

    return render_template_context("convenor/selector/project_new_offer.html", project=proj, pclass_id=proj.config.project_class.id)


@convenor.route("/new_project_offer_ajax/<int:proj_id>")
@roles_accepted("faculty", "admin", "root")
def new_project_offer_ajax(proj_id):
    # proj_id is a LiveProject
    proj = LiveProject.query.get_or_404(proj_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return jsonify({})

    state = proj.config.selector_lifecycle
    if state <= ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE:
        flash("It is not possible to set up a new custom offer before the corresponding project class has gone live.", "error")
        return redirect(redirect_url())

    # get list of available selectors
    config = proj.config
    selectors = config.selecting_students.filter(~SelectingStudent.custom_offers.any(liveproject_id=proj_id))

    return ajax.convenor.project_offer_selectors(selectors.all(), proj)


@convenor.route("/create_new_offer/<int:sel_id>/<int:proj_id>")
@roles_accepted("faculty", "admin", "root")
def create_new_offer(sel_id, proj_id):
    # proj_id is a LiveProject
    proj: LiveProject = LiveProject.query.get_or_404(proj_id)
    config: ProjectClassConfig = proj.config

    # sel_id is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sel_id)

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.selectors", id=config.pclass_id)

    # check project and selector belong to the same project class
    if proj.config_id != sel.config_id:
        flash(
            'Project "{pname}" and selector "{sname}" do not belong to the same project class, so a '
            "custom offer cannot be created for this pair.".format(pname=proj.name, sname=sel.student.user.name),
            "error",
        )
        return redirect(url)

    # check whether an offer with this selector and project already exists
    q = db.session.query(CustomOffer).filter(CustomOffer.liveproject_id == proj_id, CustomOffer.selector_id == sel_id)
    if get_count(q) > 0:
        flash(
            'A request to create a custom offer for project "{pname}" and selector "{sname}" was ignored, '
            "because an offer for this pair already exists".format(pname=proj.name, sname=sel.student.user.name),
            "info",
        )
        return redirect(url)

    offer = CustomOffer(
        liveproject_id=proj.id, selector_id=sel.id, status=CustomOffer.OFFERED, creator_id=current_user.id, creation_timestamp=datetime.now()
    )

    try:
        db.session.add(offer)
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not create custom offer due to a database error. Please contact a system administrator", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(url)


@convenor.route("/accept_custom_offer/<int:offer_id>")
@roles_accepted("faculty", "admin", "root")
def accept_custom_offer(offer_id):
    # offer_id is a CustomOffer
    offer = CustomOffer.query.get_or_404(offer_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(offer.liveproject.config.project_class):
        return redirect(redirect_url())

    if offer.selector.number_offers_accepted > 0:
        flash(
            "A custom offer has already been accepted for selector {name}. "
            "Please decline this offer before accepting a new one.".format(name=offer.selector.student.user.name),
            "error",
        )
        return redirect(redirect_url())

    offer.status = CustomOffer.ACCEPTED
    offer.last_edit_timestamp = datetime.now()
    offer.last_edit_id = current_user.id

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not mark custom offer as accepted due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/decline_custom_offer/<int:offer_id>")
@roles_accepted("faculty", "admin", "root")
def decline_custom_offer(offer_id):
    # offer_id is a CustomOffer
    offer = CustomOffer.query.get_or_404(offer_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(offer.liveproject.config.project_class):
        return redirect(redirect_url())

    offer.status = CustomOffer.DECLINED
    offer.last_edit_timestamp = datetime.now()
    offer.last_edit_id = current_user.id

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not mark custom offer as declined due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/delete_custom_offer/<int:offer_id>")
@roles_accepted("faculty", "admin", "root")
def delete_custom_offer(offer_id):
    # offer_id is a CustomOffer
    offer = CustomOffer.query.get_or_404(offer_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(offer.liveproject.config.project_class):
        return redirect(redirect_url())

    try:
        db.session.delete(offer)
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not delete custom offer due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/project_confirmations/<int:id>")
@roles_accepted("faculty", "admin", "root")
def project_confirmations(id):
    # id is a LiveProject
    proj = LiveProject.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(proj.config.project_class):
        return home_dashboard()

    return render_template_context("convenor/selector/project_confirmations.html", project=proj, now=datetime.now())


@convenor.route("/add_group_filter/<int:id>/<int:gid>")
@roles_accepted("faculty", "admin", "root")
def add_group_filter(id, gid):
    group = ResearchGroup.query.get_or_404(gid)

    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(redirect_url())

    if group not in record.group_filters:
        try:
            record.group_filters.append(group)
            db.session.commit()
        except (StaleDataError, IntegrityError):
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/remove_group_filter/<int:id>/<int:gid>")
@roles_accepted("faculty", "admin", "root")
def remove_group_filter(id, gid):
    group = ResearchGroup.query.get_or_404(gid)

    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(redirect_url())

    if group in record.group_filters:
        try:
            record.group_filters.remove(group)
            db.session.commit()
        except StaleDataError:
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/clear_group_filters/<int:id>")
@roles_accepted("faculty", "admin", "root")
def clear_group_filters(id):
    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(redirect_url())

    try:
        record.group_filters = []
        db.session.commit()
    except StaleDataError:
        # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
        # to the same endpoint?
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/add_skill_filter/<int:id>/<int:skill_id>")
@roles_accepted("faculty", "admin", "root")
def add_skill_filter(id, skill_id):
    skill = TransferableSkill.query.get_or_404(skill_id)

    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(redirect_url())

    if skill not in record.skill_filters:
        try:
            record.skill_filters.append(skill)
            db.session.commit()
        except (StaleDataError, IntegrityError):
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/remove_skill_filter/<int:id>/<int:skill_id>")
@roles_accepted("faculty", "admin", "root")
def remove_skill_filter(id, skill_id):
    skill = TransferableSkill.query.get_or_404(skill_id)

    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(redirect_url())

    if skill in record.skill_filters:
        try:
            record.skill_filters.remove(skill)
            db.session.commit()
        except StaleDataError:
            # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
            # to the same endpoint?
            db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/clear_skill_filters/<int:id>")
@roles_accepted("faculty", "admin", "root")
def clear_skill_filters(id):
    # id is a FilterRecord
    record = FilterRecord.query.get_or_404(id)

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_is_convenor(record.config.project_class):
        return redirect(redirect_url())

    try:
        record.skill_filters = []
        db.session.commit()
    except StaleDataError:
        # presumably caused by some sort of race condition; maybe two threads are invoked concurrently
        # to the same endpoint?
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/set_hint/<int:id>/<int:hint>")
@roles_accepted("faculty", "admin", "root")
def set_hint(id, hint):
    rec = SelectionRecord.query.get_or_404(id)
    config = rec.owner.config

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        flash("Selection hints may only be set once student choices are closed and the project class is ready to match", "error")
        return redirect(redirect_url())

    try:
        rec.set_hint(hint)
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not set selection hint due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/hints_list/<int:id>")
@roles_accepted("faculty", "admin", "root")
def hints_list(id):
    # pid is a ProjectClass
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    if config.selector_lifecycle < ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING:
        flash("Selection hints may only be set once student choices are closed and the project class is ready to match", "error")
        return redirect(redirect_url())

    hints = (
        db.session.query(SelectionRecord)
        .join(SelectingStudent, SelectingStudent.id == SelectionRecord.owner_id)
        .filter(SelectingStudent.config_id == config.id)
        .filter(SelectionRecord.hint != SelectionRecord.SELECTION_HINT_NEUTRAL)
        .all()
    )

    return render_template_context("convenor/dashboard/hints_list.html", pclass=pclass, hints=hints)


@convenor.route("/audit_matches/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def audit_matches(pclass_id):
    # pclass_id labels a ProjectClass
    pclass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    return render_template_context("convenor/matching/audit.html", pclass=pclass)


@convenor.route("/audit_matches_ajax/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def audit_matches_ajax(pclass_id):
    # pclass_id labels a ProjectClass
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    matches = config.published_matches.all()

    return ajax.admin.matches_data(
        matches,
        config=config,
        text="matching audit dashboard",
        url=url_for("convenor.audit_matches", pclass_id=pclass_id),
        is_root=current_user.has_role("root"),
    )


@convenor.route("/audit_schedules/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def audit_schedules(pclass_id):
    # pclass_id labels a ProjectClass
    pclass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    return render_template_context("convenor/presentations/audit.html", pclass_id=pclass_id)


@convenor.route("/audit_schedules_ajax/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def audit_schedules_ajax(pclass_id):
    # pclass_id labels a ProjectClass
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    matches = config.published_schedules.all()

    return ajax.admin.assessment_schedules_data(
        matches, text="schedule audit dashboard", url=url_for("convenor.audit_schedules", pclass_id=pclass_id)
    )


@convenor.route("/open_feedback/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def open_feedback(id):
    # id is a ProjectClassConfig
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    state = config.submitter_lifecycle
    if state != ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY and state != ProjectClassConfig.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY:
        flash("Feedback cannot be opened at this stage in the project lifecycle.", "info")
        return redirect(redirect_url())

    # get record for current submission period
    period: SubmissionPeriodRecord = config.periods.filter_by(submission_period=config.submission_period).first()
    if period is None and config.submissions > 0:
        flash("Internal error: could not locate SubmissionPeriodRecord. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    # set up instance of OpenFeedbackForm to capture form state
    if period is not None and period.is_feedback_open:
        OpenFeedbackForm = OpenFeedbackFormFactory(include_send_button=True, include_test_button=True, include_close_button=False)
    else:
        if period.collect_project_feedback:
            OpenFeedbackForm = OpenFeedbackFormFactory(include_send_button=False, include_test_button=True, include_close_button=True)
        else:
            OpenFeedbackForm = OpenFeedbackFormFactory(include_send_button=False, include_test_button=False, include_close_button=False)

    feedback_form = OpenFeedbackForm(request.form)

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    if feedback_form.is_submitted():
        deadline = feedback_form.feedback_deadline.data

        if feedback_form.submit_button.data:
            if period.feedback_open:
                response = _process_update_deadline(config, deadline, id, period, url)
            else:
                response = _open_feedback_request(config, deadline, feedback_form, id, period, url)

            if response is None:
                redirect(redirect_url())
            else:
                return response

        elif hasattr(feedback_form, "send_notifications") and feedback_form.send_notifications.data:
            return _send_feedback_notifications_request(config, deadline, feedback_form, id, period, url)

        elif hasattr(feedback_form, "test_button") and feedback_form.test_button.data:
            return _test_notifications(deadline, feedback_form, id, url)

        elif hasattr(feedback_form, "close_button") and feedback_form.close_button.data:
            return _close_period_request(config, id, period, url)

    return redirect(redirect_url())


def _test_notifications(deadline: datetime, feedback_form, id, url):
    return redirect(
        url_for(
            "convenor.test_notifications",
            id=id,
            url=url,
            deadline=deadline.isoformat(),
            cc_me=int(feedback_form.cc_me.data),
            max_attachment=int(feedback_form.max_attachment.data),
        )
    )


def _close_period_request(config: ProjectClassConfig, id, period: SubmissionPeriodRecord, url):
    if period.collect_project_feedback:
        title = "Immediately close {proj}/{period}".format(proj=config.name, period=period.display_name)
        panel_title = "Immediately close <strong>{proj}/{period}</strong> without sending marking notifications".format(
            proj=config.name, period=period.display_name
        )
        message = (
            "<p>Are you sure that you wish to immediately close <strong>{proj}/{period}</strong>?</p>"
            "<p>No marking requests will be sent, and the feedback window will be closed.<p>"
            "<p>These actions cannot be undone.</p>".format(proj=config.name, period=period.display_name)
        )
        action_url = url_for("convenor.immediate_close_feedback", id=id, url=url)
        submit_label = "Immediately close {period}".format(period=period.display_name)
        return render_template_context(
            "admin/danger_confirm.html",
            title=title,
            panel_title=panel_title,
            action_url=action_url,
            message=message,
            submit_label=submit_label,
        )

    title = "Close {proj}/{period}".format(proj=config.name, period=period.display_name)
    panel_title = "Close {proj}/{period}".format(proj=config.name, period=period.display_name)
    message = (
        "<p>Marking and feedback is not being collected online for this submission period.</p>"
        "<p><strong>{proj}/{period}</strong> will be closed, and no notifications will be sent.</p>"
        "<p>These actions cannot be undone.</p>".format(proj=config.name, period=period.display_name)
    )
    action_url = url_for("convenor.immediate_close_feedback", id=id, url=url)
    submit_label = "Close {period}".format(period=period.display_name)
    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


def _send_feedback_notifications_request(config, deadline, feedback_form, id, period, url):
    # issue confirmation request
    title = "Issue unsent marking notifications for {proj}/{period}".format(proj=config.name, period=period.display_name)
    panel_title = "Issue unsent marking notifications for <strong>{proj}/{period}</strong>".format(proj=config.name, period=period.display_name)
    message = (
        "<p>Are you sure that you wish to issue unsent marking notifications for "
        "<strong>{proj}/{period}</strong>?</p>"
        "<p>Email notifications will be issued to markers where a project report is now "
        "available, but no notification email has previously been issued.</p>"
        "<p>If no report has yet been uploaded, further email notifications can be issued at a later "
        "date when the report is available.</p>".format(proj=config.name, period=period.display_name)
    )
    action_url = url_for(
        "convenor.do_send_notifications",
        id=id,
        url=url,
        deadline=deadline.isoformat(),
        cc_me=int(feedback_form.cc_me.data),
        max_attachment=int(feedback_form.max_attachment.data),
    )
    submit_label = "Issue unsent marking notifications"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


def _open_feedback_request(config, deadline, feedback_form, id, period, url):
    if not period.collect_project_feedback:
        return _close_period_request(config, id, period, url)

    if deadline is None:
        flash(
            f"The submission deadline was not processed correctly (stored value = {deadline}). "
            f"If this issue persists, please contact a system administrator."
        )
        return None

    # issue confirmation request
    title = "Open feedback for {proj}/{period}".format(proj=config.name, period=period.display_name)
    panel_title = "Open feedback for <strong>{proj}/{period}</strong> and issue email notifications to markers".format(
        proj=config.name, period=period.display_name
    )
    message = (
        "<p>Are you sure that you wish to open <strong>{proj}/{period}</strong> for feedback?</p>"
        "<p>The marking deadline will be set to <strong>{deadline}</strong> and email "
        "notifications will be issued to markers where a project report has already been "
        "uploaded.</p>"
        "<p>If no report has yet been uploaded, email notifications can be issued at a later date "
        "when the report is available.</p>"
        "<p>These actions cannot be "
        "undone.</p>".format(proj=config.name, period=period.display_name, deadline=deadline.strftime("%a %d %b %Y"))
    )
    action_url = url_for(
        "convenor.do_open_feedback",
        id=id,
        url=url,
        deadline=deadline.isoformat(),
        cc_me=int(feedback_form.cc_me.data),
        max_attachment=int(feedback_form.max_attachment.data),
    )
    submit_label = "Open feedback and issue notifications"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


def _process_update_deadline(config: ProjectClassConfig, deadline, id, period: SubmissionPeriodRecord, url):
    if not period.collect_project_feedback:
        return _close_period_request(config, id, period, url)

    if deadline is None:
        flash(
            f"The submission deadline was not processed correctly (stored value = {deadline}). "
            f"If this issue persists, please contact a system administrator."
        )
        return None

    # if feedback is already open, nothing to do but change the deadline
    period.feedback_deadline = deadline

    try:
        db.session.commit()
        flash(
            "The feedback deadline for {proj}/{period} has been successfully changed "
            "to {deadline}.".format(proj=config.name, period=period.display_name, deadline=deadline.strftime("%a %d %b %Y")),
            "success",
        )
    except SQLAlchemyError as e:
        flash("Could not modify feedback status due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return None


@convenor.route("/test_notifications/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def test_notifications(id):
    # id is a ProjectClassConfig
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    state = config.submitter_lifecycle
    if state != ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY and state != ProjectClassConfig.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY:
        flash("Feedback cannot be opened at this stage in the project lifecycle.", "info")
        return redirect(redirect_url())

    # get record for current submission period
    period: SubmissionPeriodRecord = config.periods.filter_by(submission_period=config.submission_period).first()
    if period is None and config.submissions > 0:
        flash("Internal error: could not locate SubmissionPeriodRecord. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    cc_me = bool(int(request.args.get("cc_me", 0)))
    max_attachment = int(request.args.get("max_attachment", 2))
    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.status", id=config.pclass_id)

    deadline = request.args.get("deadline", None)
    if deadline is None:
        flash(
            "A request to open feedback was ignored because the deadline was not correctly received. "
            "Please report this issue to an administrator.",
            "error",
        )
        return redirect(url)

    form = TestOpenFeedbackForm(request.form)

    if form.validate_on_submit():
        test_email = form.target_email.data

        return redirect(
            url_for(
                "convenor.do_send_notifications",
                id=id,
                url=url,
                deadline=deadline,
                cc_me=int(cc_me),
                max_attachment=int(max_attachment),
                test_email=str(test_email),
            )
        )

    return render_template_context(
        "convenor/dashboard/test_notifications.html",
        url=url,
        deadline=deadline,
        cc_me=int(cc_me),
        max_attachment=int(max_attachment),
        form=form,
        config=config,
    )


@convenor.route("/do_send_notifications/<int:id>")
@roles_accepted("faculty", "admin", "root")
def do_send_notifications(id):
    # id is a ProjectClassConfig
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    state = config.submitter_lifecycle
    if state != ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY and state != ProjectClassConfig.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY:
        flash("Feedback cannot be opened at this stage in the project lifecycle.", "info")
        return redirect(redirect_url())

    # get record for current submission period
    period: SubmissionPeriodRecord = config.periods.filter_by(submission_period=config.submission_period).first()
    if period is None and config.submissions > 0:
        flash("Internal error: could not locate SubmissionPeriodRecord. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    cc_me = bool(int(request.args.get("cc_me", 0)))
    max_attachment = int(request.args.get("max_attachment", 2))
    test_email = request.args.get("test_email", None)
    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.status", id=config.pclass_id)

    deadline = request.args.get("deadline", None)
    if deadline is None:
        flash(
            "A request to open feedback was ignored because the deadline was not correctly received. "
            "Please report this issue to an administrator.",
            "error",
        )
        return redirect(url)

    celery = current_app.extensions["celery"]
    marking_email = celery.tasks["app.tasks.marking.send_marking_emails"]

    tk_name = "Dispatch marking notifications"
    tk_description = "Dispatch emails with reports and marking instructions"

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    seq = chain(
        init.si(task_id, tk_name),
        marking_email.si(period.id, cc_me, max_attachment, test_email, deadline, current_user.id),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(url)


@convenor.route("/do_open_feedback/<int:id>")
@roles_accepted("faculty", "admin", "root")
def do_open_feedback(id):
    # id is a ProjectClassConfig
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    state = config.submitter_lifecycle
    if state != ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY and state != ProjectClassConfig.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY:
        flash("Feedback cannot be opened at this stage in the project lifecycle.", "info")
        return redirect(redirect_url())

    # get record for current submission period
    period: SubmissionPeriodRecord = config.periods.filter_by(submission_period=config.submission_period).first()
    if period is None and config.submissions > 0:
        flash("Internal error: could not locate SubmissionPeriodRecord. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    cc_me = bool(int(request.args.get("cc_me", 0)))
    max_attachment = int(request.args.get("max_attachment", 2))
    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.periods", id=config.pclass_id)

    deadline = request.args.get("deadline", None)
    if deadline is None:
        flash(
            "A request to open feedback was ignored because the deadline was not correctly received. "
            "Please report this issue to an administrator.",
            "error",
        )
        return redirect(url)

    deadline = parser.parse(deadline).date()

    # set feedback deadline and mark feedback open
    period.feedback_open = True
    period.feedback_deadline = deadline

    # mark current user as the person who opened feedback, if it is currently unset
    if period.feedback_id is None:
        period.feedback_id = current_user.id

    # set timestamp, if it is currrently unset
    if period.feedback_timestamp is None:
        period.feedback_timestamp = datetime.now()

    try:
        db.session.commit()
        flash(
            'Feedback for "{proj}" has been opened successfully, with deadline '
            "{deadline}.".format(proj=config.name, deadline=period.feedback_deadline.strftime("%a %d %b %Y")),
            "success",
        )
    except SQLAlchemyError as e:
        flash("Could not open feedback due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()
        return redirect(url)

    celery = current_app.extensions["celery"]
    marking_email = celery.tasks["app.tasks.marking.send_marking_emails"]

    tk_name = "Dispatch marking notifications"
    tk_description = "Dispatch emails with reports and marking instructions"

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    seq = chain(
        init.si(task_id, tk_name),
        marking_email.si(period.id, cc_me, max_attachment, None, deadline.isoformat(), current_user.id),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(url)


@convenor.route("/immediate_close_feedback/<int:id>")
@roles_accepted("faculty", "admin", "root")
def immediate_close_feedback(id):
    # id is a ProjectClassConfig
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    state = config.submitter_lifecycle
    if state != ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY and state != ProjectClassConfig.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY:
        flash("Feedback cannot be closed at this stage in the project lifecycle.", "info")
        return redirect(redirect_url())

    if config.submission_period > config.submissions:
        flash('Feedback close request ignored because "{name}" ' "is already in a rollover state.".format(name=config.name), "info")
        return request.referrer

    # get record for current submission period
    period: SubmissionPeriodRecord = config.periods.filter_by(submission_period=config.submission_period).first()
    if period is None and config.submissions > 0:
        flash("Internal error: could not locate SubmissionPeriodRecord. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.periods", id=config.pclass_id)

    now = datetime.now()

    period.feedback_open = True
    period.feedback_deaedline = now
    period.feedback_id = current_user.id
    period.feedback_timestamp = now

    period.closed = True
    period.closed_id = current_user.id
    period.closed_timestamp = now

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not modify feedback status due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(url)


@convenor.route("/close_feedback/<int:id>")
@roles_accepted("faculty", "admin", "root")
def close_feedback(id):
    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    state = config.submitter_lifecycle
    if state != ProjectClassConfig.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY:
        flash("Feedback cannot be closed at this stage in the project lifecycle.", "info")
        return redirect(redirect_url())

    if config.submission_period > config.submissions:
        flash('Feedback close request ignored because "{name}" ' "is already in a rollover state.".format(name=config.name), "info")
        return request.referrer

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    title = 'Close feedback for "{name}"'.format(name=config.name)
    panel_title = "Close feedback for <strong>{name}</strong>".format(name=config.name)

    action_url = url_for("convenor.do_close_feedback", id=id, url=url)
    message = (
        "<p>Are you sure that you wish to close feedback for project class "
        "<strong>{name}</strong>?</p>"
        "<p>After closure, no immediate action is taken automatically by the platform. "
        "Feedback becomes available to push to students when required.</p>"
        "<p>This action cannot be undone.</p>".format(name=config.name)
    )
    submit_label = "Close feedback"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@convenor.route("/do_close_feedback/<int:id>")
@roles_accepted("faculty", "admin", "root")
def do_close_feedback(id):
    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    state = config.submitter_lifecycle
    if state != ProjectClassConfig.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY:
        flash("Feedback cannot be closed at this stage in the project lifecycle.", "info")
        return redirect(redirect_url())

    if config.submission_period > config.submissions:
        flash('Feedback close request ignored because "{name}" ' "is already in a rollover state.".format(name=config.name), "info")
        return request.referrer

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    period: SubmissionPeriodRecord = config.periods.filter_by(submission_period=config.submission_period).first()
    if period is None and config.submissions > 0:
        flash("Internal error: could not locate SubmissionPeriodRecord. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    period.closed = True
    period.closed_id = current_user.id
    period.closed_timestamp = datetime.now()

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not modify feedback status due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(url)


@convenor.route("/edit_project_config/<int:pid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_project_config(pid):
    # pid is a ProjectClassConfig
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(pid)

    # reject is user is not a convenor for the associated project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # check configuration is still current
    if config.project_class.most_recent_config.id != config.id:
        flash(
            "It is no longer possible to edit the project configuration for academic year {yra}&ndash;{yrb} "
            "because it has been rolled over.".format(yra=config.submit_year_a, yrb=config.submit_year_b),
            "info",
        )
        return redirect(redirect_url())

    EditProjectConfigForm = EditProjectConfigFormFactory(config)
    form = EditProjectConfigForm(obj=config)

    if form.validate_on_submit():
        now = datetime.now()

        if form.skip_matching.data != config.skip_matching:
            config.skip_matching = form.skip_matching.data

        if form.requests_skipped.data != config.requests_skipped:
            config.requests_skipped = form.requests_skipped.data

            if config.requests_skipped:
                config.requests_skipped_id = current_user.id
                config.requests_skipped_timestamp = now
            else:
                config.requests_skipped_by = None
                config.requests_skipped_timestamp = None

        if form.full_CATS.data != config.full_CATS:
            config.full_CATS = form.full_CATS.data

        use_hub = form.project_hub_value_map[form.use_project_hub.data]
        if use_hub != config.use_project_hub:
            config.use_project_hub = use_hub

        config.uses_supervisor = form.uses_supervisor.data
        config.uses_marker = form.uses_marker.data
        config.uses_moderator = form.uses_moderator.data
        config.uses_presentations = form.uses_presentations.data
        config.display_marker = form.display_marker.data
        config.display_presentations = form.display_presentations.data

        config.CATS_supervision = form.CATS_supervision.data
        config.CATS_marking = form.CATS_marking.data
        config.CATS_moderation = form.CATS_moderation.data
        config.CATS_presentation = form.CATS_presentation.data

        if hasattr(form, "canvas_module_id"):
            config.canvas_module_id = form.canvas_module_id.data
        if hasattr(form, "canvas_login"):
            config.canvas_login = form.canvas_login.data

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash("Could not save project configuration because of a database error. Please contact a system administrator.", "error")
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("convenor.status", id=config.project_class.id))

    else:
        if request.method == "GET":
            value = config.use_project_hub
            if value not in form.project_hub_choice_map.keys():
                value = None
            form.use_project_hub.data = form.project_hub_choice_map[value]

    return render_template_context("convenor/dashboard/edit_project_config.html", form=form, config=config)


def _validate_submission_period(record: SubmissionPeriodRecord, config: ProjectClassConfig):
    # reject is user is not a convenor for the associated project class
    if not validate_is_convenor(config.project_class):
        return False

    # check configuration is still current
    if config.project_class.most_recent_config.id != config.id:
        flash(
            "It is no longer possible to edit the project configuration for academic year {yra}&ndash;{yrb} "
            "because it has been rolled over.".format(yra=config.submit_year_a, yrb=config.submit_year_b),
            "info",
        )
        return False

    # reject if project class is not published
    if not validate_project_class(config.project_class):
        return False

    # reject if this submission period is in the past
    if config.submission_period > record.submission_period:
        flash("It is no longer possible to edit this submission period because it has been closed.", "info")
        return False

    # reject if period is retired
    if record.retired:
        flash("It is no longer possible to edit this submission period because it has been retired.", "info")
        return False

    # reject if lifecycle stage is marking or later

    state = config.submitter_lifecycle
    if state >= ProjectClassConfig.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY:
        flash("It is no longer possible to edit this submission period because it is being marked, or is ready to rollover.", "info")
        return False

    return True


@convenor.route("/edit_period_record/<int:pid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_period_record(pid):
    # pid is a SubmissionPeriodRecord
    record: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)
    config: ProjectClassConfig = record.config

    if not _validate_submission_period(record, config):
        return redirect(redirect_url())

    FormClass = EditPeriodRecordFormFactory(config)
    edit_form = FormClass(obj=record)

    if edit_form.validate_on_submit():
        record.name = edit_form.name.data
        record.number_markers = edit_form.number_markers.data
        record.number_moderators = edit_form.number_moderators.data
        record.start_date = edit_form.start_date.data
        record.hand_in_date = edit_form.hand_in_date.data

        record.collect_project_feedback = edit_form.collect_project_feedback.data

        if hasattr(edit_form, "canvas_module_id"):
            record.canvas_module_id = edit_form.canvas_module_id.data
        if hasattr(edit_form, "canvas_assignment_id"):
            record.canvas_assignment_id = edit_form.canvas_assignment_id.data

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash("Could not save submission period configuration because of a database error. Please contact a system administrator.", "error")
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("convenor.periods", id=config.project_class.id))

    return render_template_context("convenor/dashboard/edit_period_record.html", form=edit_form, record=record, config=config)


@convenor.route("/edit_period_presentation/<int:pid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_period_presentation(pid):
    # pid is a SubmissionPeriodRecord
    record: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)
    config: ProjectClassConfig = record.config

    if not _validate_submission_period(record, config):
        return redirect(redirect_url())

    edit_form = EditSubmissionPeriodRecordPresentationsForm(obj=record)

    if edit_form.validate_on_submit():
        record.has_presentation = edit_form.has_presentation.data

        if record.has_presentation:
            record.lecture_capture = edit_form.lecture_capture.data
            record.collect_presentation_feedback = edit_form.collect_presentation_feedback.data
            record.number_assessors = edit_form.number_assessors.data
            record.max_group_size = edit_form.max_group_size.data
            record.morning_session = edit_form.morning_session.data
            record.afternoon_session = edit_form.afternoon_session.data
            record.talk_format = edit_form.talk_format.data

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash("Could not save submission period configuration because of a database error. Please contact a system administrator.", "error")
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("convenor.periods", id=config.project_class.id))

    return render_template_context("convenor/dashboard/edit_period_presentation.html", form=edit_form, record=record)


@convenor.route("/publish_assignment/<int:id>")
@roles_accepted("faculty", "admin", "root")
def publish_assignment(id):
    # id is a SubmittingStudent
    sub = SubmittingStudent.query.get_or_404(id)

    # reject if project class not published
    if not validate_project_class(sub.config.project_class):
        return redirect(redirect_url())

    # reject if logged-in user is not a convenor for this SubmittingStudent
    if not validate_is_convenor(sub.config.project_class):
        return redirect(redirect_url())

    if sub.config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash("It is now too late to publish an assignment to students for this project class.", "error")
        return redirect(redirect_url())

    sub.published = True

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not publish assignment because of a database error. Please contact a system administrator.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/unpublish_assignment/<int:id>")
@roles_accepted("faculty", "admin", "root")
def unpublish_assignment(id):
    # id is a SubmittingStudent
    sub = SubmittingStudent.query.get_or_404(id)

    # reject if logged-in user is not a convenor for this SubmittingStudent
    if not validate_is_convenor(sub.config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(sub.config.project_class):
        return redirect(redirect_url())

    if sub.config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash("It is now too late to unpublish an assignment for this project class.", "error")
        return redirect(redirect_url())

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not unpublish assignment because of a database error. Please contact a system administrator.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/publish_all_assignments/<int:id>")
@roles_accepted("faculty", "admin", "root")
def publish_all_assignments(id):
    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # reject if logged-in user is not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    if config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash("It is now too late to publish assignments to students for this project class.", "error")
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    year_filter = request.args.get("year_filter")

    data = build_submitters_data(config, cohort_filter, prog_filter, state_filter, year_filter)

    for sel in data:
        sel.published = True

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not publish assignments because of a database error. Please contact a system administrator.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/unpublish_all_assignments/<int:id>")
@roles_accepted("faculty", "admin", "root")
def unpublish_all_assignments(id):
    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # reject if logged-in user is not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    if config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash("It is now too late to unpublish assignments for this project class.", "error")
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    year_filter = request.args.get("year_filter")

    data = build_submitters_data(config, cohort_filter, prog_filter, state_filter, year_filter)

    for sel in data:
        sel.published = False

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not unpublish assignments because of a database error. Please contact a system administrator.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/mark_started/<int:id>")
@roles_accepted("faculty", "admin", "root")
def mark_started(id):
    # id is a SubmissionRecord
    rec = SubmissionRecord.query.get_or_404(id)

    # reject if logged-in user is not a convenor for the project class associated with this submission record
    if not validate_is_convenor(rec.owner.config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(rec.owner.config.project_class):
        return redirect(redirect_url())

    if rec.owner.config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash('It is now too late to mark a submission period as "started" for this project class.', "error")
        return redirect(redirect_url())

    if rec.submission_period > rec.owner.config.submission_period:
        flash("Cannot mark this submission period as started because it is not yet open.", "error")
        return redirect(redirect_url())

    if not rec.owner.published:
        flash("Cannot mark this submission period as started because it is not published to the submitter.", "error")
        return redirect(redirect_url())

    rec.student_engaged = True

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash('Could not mark student "started" because of a database error. ' "Please contact a system administrator.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/mark_all_started/<int:id>")
@roles_accepted("faculty", "admin", "root")
def mark_all_started(id):
    # id is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(id)

    # reject if logged-in user is not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(redirect_url())

    if config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash("It is now too late to mark students as started.", "error")
        return redirect(redirect_url())

    cohort_filter = request.args.get("cohort_filter")
    prog_filter = request.args.get("prog_filter")
    state_filter = request.args.get("state_filter")
    year_filter = request.args.get("year_filter")

    data = build_submitters_data(config, cohort_filter, prog_filter, state_filter, year_filter)

    for sub in data:
        sub: SubmittingStudent
        if sub.published:
            record: SubmissionRecord = sub.get_assignment(config.submission_period)
            if record is not None and record.project_id is not None:
                record.student_engaged = True

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash('Could not mark students "started" because of a database error. ' "Please contact a system administrator.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/mark_waiting/<int:id>")
@roles_accepted("faculty", "admin", "root")
def mark_waiting(id):
    # id is a SubmissionRecord
    rec = SubmissionRecord.query.get_or_404(id)

    # reject if logged-in user is not a convenor for the project class associated with this submission record
    if not validate_is_convenor(rec.owner.config.project_class):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(rec.owner.config.project_class):
        return redirect(redirect_url())

    if rec.owner.config.submitter_lifecycle >= ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER:
        flash('It is now too late to mark a submission period as "waiting" for this project class.', "error")
        return redirect(redirect_url())

    if rec.submission_period > rec.owner.config.submission_period:
        flash("Cannot mark this submission period as started because it is not yet open.", "error")
        return redirect(redirect_url())

    if not rec.owner.published:
        flash("Cannot mark this submission period as started because it is not published to the submitter.", "error")
        return redirect(redirect_url())

    rec.student_engaged = False

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash('Could not mark student "waiting" because of a database error. ' "Please contact a system administrator.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@convenor.route("/populate_markers/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def populate_markers(configid):
    # configid is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(configid)

    # reject if logged-in user is not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    uuid = register_task(
        'Populate markers for "{proj}"'.format(proj=config.name),
        owner=current_user,
        description="Populate missing marker assignments for " '"{proj}"'.format(proj=config.name),
    )

    celery = current_app.extensions["celery"]
    populate = celery.tasks["app.tasks.matching.populate_markers"]

    populate.apply_async(args=(config.id, current_user.id, uuid), task_id=uuid)

    return redirect(redirect_url())


@convenor.route("/remove_markers/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def remove_markers(configid):
    # configid is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(configid)

    # reject if logged-in user is not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    title = "Remove all markers"
    panel_title = "Remove all markers"

    action_url = url_for("convenor.do_remove_markers", configid=configid, url=url)
    message = "<p>Are you sure that you wish to remove all marker assignments?</p>" "<p>This action cannot be undone.</p>"
    submit_label = "Remove markers"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@convenor.route("/do_remove_markers/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def do_remove_markers(configid):
    # configid is a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(configid)

    # reject if logged-in user is not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    uuid = register_task(
        'Remove markers for "{proj}"'.format(proj=config.name),
        owner=current_user,
        description="Remove marker assignments for " '"{proj}"'.format(proj=config.name),
    )

    celery = current_app.extensions["celery"]
    populate = celery.tasks["app.tasks.matching.remove_markers"]

    populate.apply_async(args=(config.id, current_user.id, uuid), task_id=uuid)

    return redirect(url)


@convenor.route("/view_feedback/", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def view_feedback():
    sub_id = request.args.get("sub_id", None)
    sid = request.args.get("id", None)

    # reject request if neither sub_id nor sid is specified
    if sub_id is None and sid is None:
        abort(404)

    submitter: SubmittingStudent = SubmittingStudent.query.get_or_404(sub_id) if sub_id is not None else None
    rec: SubmissionRecord = SubmissionRecord.query.get_or_404(sid) if sid is not None else None

    if submitter is not None:
        config: ProjectClassConfig = submitter.config
    else:
        config: ProjectClassConfig = rec.period.config

    # construct selector form
    is_admin = validate_is_convenor(config.project_class, message=False)
    SelectSubmissionRecordForm = SelectSubmissionRecordFormFactory(config, is_admin)
    form: SelectSubmissionRecordForm = SelectSubmissionRecordForm(request.form)

    # if submitter and record are both specified, check that SubmissionRecord belongs to it.
    # otherwise, we select the SubmissionRecord corresponding to the current period
    if submitter is not None:
        if rec is not None:
            if rec.owner.id != submitter.id:
                flash(
                    "Cannot display submitter documents for this combination of student and submission record, "
                    "because the specified submission record does not belong to the student",
                    "info",
                )
                return redirect(redirect_url())

        else:
            if hasattr(form, "selector") and form.selector.data is not None:
                rec: SubmissionRecord = submitter.get_assignment(period=form.selector.data)
            else:
                rec: SubmissionRecord = submitter.get_assignment()

    else:
        # submitter was not specified, so SubmissionRecord must have been.
        # we extract the SubmittingStudent from the record
        assert rec is not None
        submitter = rec.owner

    # reject if logged-in user is not a convenor for the project class associated with this submission record
    pclass = config.project_class

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # reject if project class not published
    if not validate_project_class(pclass):
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    # ensure form selector reflects the record that is actually being displayed
    if hasattr(form, "selector"):
        period: SubmissionPeriodRecord = rec.period
        form.selector.data = period

    return render_template_context("convenor/dashboard/view_feedback.html", submitter=submitter, record=rec, form=form, text=text, url=url)


@convenor.route("/faculty_workload/<int:id>")
@roles_accepted("faculty", "admin", "root")
def faculty_workload(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    enroll_filter = request.args.get("enroll_filter")

    if enroll_filter is None and session.get("convenor_faculty_enroll_filter"):
        enroll_filter = session["convenor_faculty_enroll_filter"]

    if enroll_filter not in [
        "all",
        "supv-active",
        "supv-sabbatical",
        "supv-exempt",
        "mark-active",
        "mark-sabbatical",
        "mark-exempt",
        "pres-active",
        "pres-sabbatical",
        "pres-exempt",
    ]:
        enroll_filter = "all"

    if enroll_filter is not None:
        session["convenor_faculty_enroll_filter"] = enroll_filter

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/workload.html",
        pane="faculty",
        subpane="workload",
        pclass=pclass,
        config=config,
        current_year=current_year,
        convenor_data=data,
        enroll_filter=enroll_filter,
    )


@convenor.route("faculty_workload_ajax/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def faculty_workload_ajax(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    enroll_filter = request.args.get("enroll_filter")

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return jsonify({})

    # build a list of only enrolled faculty, together with their FacultyData records
    faculty_ids = db.session.query(EnrollmentRecord.owner_id).filter(EnrollmentRecord.pclass_id == id)

    if enroll_filter == "supv-active":
        faculty_ids = faculty_ids.filter(EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED)
    elif enroll_filter == "supv-sabbatical":
        faculty_ids = faculty_ids.filter(EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_SABBATICAL)
    elif enroll_filter == "supv-exempt":
        faculty_ids = faculty_ids.filter(EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_EXEMPT)
    elif enroll_filter == "mark-active":
        faculty_ids = faculty_ids.filter(EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_ENROLLED)
    elif enroll_filter == "mark-sabbatical":
        faculty_ids = faculty_ids.filter(EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_SABBATICAL)
    elif enroll_filter == "mark-exempt":
        faculty_ids = faculty_ids.filter(EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_EXEMPT)
    elif enroll_filter == "pres-active":
        faculty_ids = faculty_ids.filter(EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED)
    elif enroll_filter == "pres-sabbatical":
        faculty_ids = faculty_ids.filter(EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_SABBATICAL)
    elif enroll_filter == "pres-exempt":
        faculty_ids = faculty_ids.filter(EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_EXEMPT)

    faculty_ids = faculty_ids.subquery()

    # get User, FacultyData pairs for this list
    base_query = (
        db.session.query(User, FacultyData)
        .filter(User.active)
        .join(FacultyData, FacultyData.id == User.id)
        .join(faculty_ids, User.id == faculty_ids.c.owner_id)
    )

    def search_name(row):
        u: User
        fd: FacultyData
        u, fd = row

        return u.name

    def sort_name(row):
        u: User
        fd: FacultyData
        u, fd = row

        return [u.last_name, u.first_name]

    def sort_workload(row):
        u: User
        fd: FacultyData
        u, fd = row

        CATS_sup, CATS_mark, CATS_moderate, CATS_pres = fd.CATS_assignment(config)
        return CATS_sup + CATS_mark + CATS_moderate + CATS_pres

    name = {"search": search_name, "order": sort_name}
    workload = {"order": sort_workload}
    columns = {"name": name, "workload": workload}

    with ServerSideInMemoryHandler(request, base_query, columns) as handler:
        return handler.build_payload(partial(ajax.convenor.faculty_workload_data, config))


@convenor.route("/teaching_groups/<int:id>")
@roles_accepted("faculty", "admin", "root")
def teaching_groups(id):
    # id is a ProjectClass
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    # get current academic year
    current_year = get_current_year()

    organize_by = request.args.get("organize_by")

    if organize_by is None and session.get("convenor_groups_organize_by"):
        organize_by = session["convenor_groups_organize_by"]

    if organize_by not in ["student", "faculty"]:
        organize_by = "faculty"

    if organize_by is not None:
        session["convenor_groups_organize_by"] = organize_by

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return redirect(redirect_url())

    # build list of allowed submission periods
    periods = set()
    period_names = OrderedSet()
    for p in config.ordered_periods:
        periods.add(p.submission_period)
        period_names.append((p.submission_period, p.display_name))

    if len(periods) == 0:
        flash("Internal error: No submission periods have been set up for this ProjectClassConfig. Please contact a system administator.", "error")
        return redirect(redirect_url())

    show_period = request.args.get("show_period")
    if show_period is not None and not isinstance(show_period, int):
        show_period = int(show_period)

    if show_period is None and session.get("convenor_groups_show_period"):
        show_period = session["convenor_groups_show_period"]

    if show_period not in periods:
        # get first allowed elmeent of periods
        for x in periods:
            break

        show_period = x

    if show_period is not None:
        session["convenor_groups_show_period"] = show_period

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/teaching_groups.html",
        pane="faculty",
        subpane="groups",
        pclass=pclass,
        config=config,
        current_year=current_year,
        convenor_data=data,
        organize_by=organize_by,
        show_period=show_period,
        period_names=period_names,
    )


@convenor.route("/teaching_groups_ajax/<int:id>")
@roles_accepted("faculty", "admin", "root")
def teaching_groups_ajax(id):
    # id is a ProjectClass
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project class
    if not validate_is_convenor(pclass):
        return jsonify({})

    organize_by = request.args.get("organize_by")

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
        return jsonify({})

    if organize_by not in ["student", "faculty"]:
        organize_by = "faculty"

    # build list of allowed submission periods
    periods = set()
    period_names = OrderedSet()
    for p in config.ordered_periods:
        periods.add(p.submission_period)
        period_names.append((p.submission_period, p.display_name))

    if len(periods) == 0:
        return jsonify({})

    show_period = request.args.get("show_period")
    if show_period is not None and not isinstance(show_period, int):
        show_period = int(show_period)

    if show_period not in periods:
        # get first allowed element of periods
        for x in periods:
            break

        show_period = x

    if organize_by == "faculty":
        faculty_ids = db.session.query(EnrollmentRecord.owner_id).filter(EnrollmentRecord.pclass_id == id).subquery()

        faculty = (
            db.session.query(FacultyData)
            .join(faculty_ids, FacultyData.id == faculty_ids.c.owner_id)
            .join(User, User.id == FacultyData.id)
            .filter(User.active)
            .all()
        )

        return ajax.convenor.teaching_group_by_faculty(faculty, config, show_period)

    return ajax.convenor.teaching_group_by_student(config.submitting_students, config, show_period)


@convenor.route("/manual_assign/", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def manual_assign():
    sub_id = request.args.get("sub_id", None)
    sid = request.args.get("id", None)

    # reject request if neither sub_id nor sid is specified
    if sub_id is None and sid is None:
        abort(404)

    submitter: SubmittingStudent = SubmittingStudent.query.get_or_404(sub_id) if sub_id is not None else None
    rec: SubmissionRecord = SubmissionRecord.query.get_or_404(sid) if sid is not None else None

    if submitter is not None:
        current_config: ProjectClassConfig = submitter.config
    else:
        current_config: ProjectClassConfig = rec.period.config

    # construct selector form
    is_admin = validate_is_convenor(current_config.project_class, message=False)
    ManualAssignForm = ManualAssignFormFactory(current_config, is_admin)
    form = ManualAssignForm(request.form)

    # if submitter and record are both specified, check that SubmissionRecord belongs to it.
    # otherwise, we select the SubmissionRecord corresponding to the current period
    if submitter is not None:
        if rec is not None:
            if rec.owner.id != submitter.id:
                flash(
                    "Cannot display submitter documents for this combination of student and submission record, "
                    "because the specified submission record does not belong to the student",
                    "info",
                )
                return redirect(redirect_url())

        else:
            if hasattr(form, "selector") and form.selector.data is not None:
                rec: SubmissionRecord = submitter.get_assignment(period=form.selector.data)
            else:
                rec: SubmissionRecord = submitter.get_assignment()

    else:
        # submitter was not specified, so SubmissionRecord must have been.
        # we extract the SubmittingStudent from the record
        assert rec is not None
        submitter = rec.owner

    # find the ProjectClassConfig from which we will draw the list of available LiveProjects
    # (this could be the current one or a previous one, depending on when the student selected, and whether
    # selection occurs in a previous cycle)
    select_config = rec.selector_config
    if select_config is None:
        flash("Can not reassign because the list of available Live Projects could not be found", "error")
        return redirect(redirect_url())

    # reject if logged-in user is not *currently* a convenor for the project class associated with this submission
    # record (note they don't have to be the historical convenor associated with select_config)
    pclass = current_config.project_class

    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    text = request.args.get("text", None)
    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    # ensure form selector reflects the record that is actually being displayed
    period: SubmissionPeriodRecord = rec.period
    if hasattr(form, "selector"):
        form.selector.data = period

    return render_template_context(
        "convenor/dashboard/manual_assign.html",
        rec=rec,
        config=select_config,
        url=url,
        text=text,
        form=form,
        submitter=submitter,
        allow_reassign_project=rec.project_id is None or (not period.is_feedback_open and not rec.student_engaged),
    )


@convenor.route("/manual_assign_ajax/<int:id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def manual_assign_ajax(id):
    # id is a SubmissionRecord
    rec: SubmissionRecord = SubmissionRecord.query.get_or_404(id)

    # find the ProjectClassConfig from which we will draw the list of available LiveProjects
    # (this could be the current one or a previous one, depending on when the student selected, and whether
    # selection occurs in a previous cycle)
    select_config = rec.selector_config
    if select_config is None:
        flash("Can not reassign because the list of available Live Projects could not be found", "error")
        return jsonify({})

    if not validate_is_convenor(select_config.project_class):
        return jsonify({})

    base_query = select_config.live_projects.join(FacultyData, FacultyData.id == LiveProject.owner_id).join(User, User.id == FacultyData.id)

    project = {"search": LiveProject.name, "order": LiveProject.name, "search_collation": "utf8_general_ci"}
    supervisor = {
        "search": func.concat(User.first_name, " ", User.last_name),
        "order": [User.last_name, User.first_name],
        "search_collation": "utf8_general_ci",
    }

    columns = {"project": project, "supervisor": supervisor}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(partial(ajax.convenor.manual_assign_data, rec))


@convenor.route("/assign_revert/<int:id>")
@roles_accepted("faculty", "admin", "root")
def assign_revert(id):
    # id is a SubmissionRecord
    rec: SubmissionRecord = SubmissionRecord.query.get_or_404(id)

    # find the ProjectClassConfig from which we will draw the list of available LiveProjects
    # (this could be the current one or a previous one, depending on when the student selected, and whether
    # selection occurs in a previous cycle)
    select_config = rec.selector_config
    if select_config is None:
        flash("Can not revert assignment because the list of available Live Projects could not be found", "error")
        return redirect(redirect_url())

    if not validate_is_convenor(select_config.project_class):
        return redirect(redirect_url())

    if rec.period.is_feedback_open:
        flash("Can not revert assignment for {name} because feedback is already open".format(name=rec.period.display_name), "error")
        return redirect(redirect_url())

    if rec.student_engaged:
        flash("Can not revert assignment for {name} because the project is already marked as started".format(name=rec.period.display_name), "error")
        return redirect(redirect_url())

    if rec.matching_record is None:
        flash(
            "Can not revert assignment for {name} because the automated matching data could not be found".format(name=rec.period.display_name),
            "error",
        )
        return redirect(redirect_url())

    now = datetime.now()

    try:
        # remove any SubmissionRole instances for supervisor, marker and moderator
        rec.roles.filter(
            or_(
                SubmissionRole.role == SubmissionRole.ROLE_SUPERVISOR,
                SubmissionRole.role == SubmissionRole.ROLE_MARKER,
                SubmissionRole.role == SubmissionRole.ROLE_MODERATOR,
            )
        ).delete()

        match_record: MatchingRecord = rec.matching_record
        lp = match_record.project
        rec.project_id = lp.id

        for role in match_record.roles:
            role: MatchingRole
            new_role = SubmissionRole(
                submission_id=rec.id,
                user_id=role.user_id,
                role=role.role,
                marking_email=False,
                positive_feedback=None,
                improvements_feedback=None,
                submitted_feedback=False,
                feedback_timestamp=None,
                acknowledge_student=False,
                response=None,
                submitted_response=False,
                response_timestamp=None,
                creator_id=None,
                creation_timestamp=now,
                last_edit_id=None,
                last_edit_timestamp=None,
            )

            db.session.add(new_role)

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not revert assignment to match because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@convenor.route("/assign_from_selection/<int:id>/<int:sel_id>")
@roles_accepted("faculty", "admin", "root")
def assign_from_selection(id, sel_id):
    # id is a SubmissionRecord
    rec: SubmissionRecord = SubmissionRecord.query.get_or_404(id)

    # find the ProjectClassConfig from which we will draw the list of available LiveProjects
    # (this could be the current one or a previous one, depending on when the student selected, and whether
    # selection occurs in a previous cycle)
    select_config = rec.selector_config
    if select_config is None:
        flash("Can not reassign because the list of available Live Projects could not be found", "error")
        return redirect(redirect_url())

    if not validate_is_convenor(select_config.project_class):
        return redirect(redirect_url())

    if rec.period.is_feedback_open:
        flash("Can not reassign for {name} because feedback is already open".format(name=rec.period.display_name), "error")
        return redirect(redirect_url())

    if rec.student_engaged and rec.project_id is not None:
        flash("Can not reassign for {name} because the project is already marked as started".format(name=rec.period.display_name), "error")
        return redirect(redirect_url())

    sel = SelectionRecord.query.get_or_404(sel_id)

    try:
        # remove any SubmissionRole instances which have the owner as supervisor
        if rec.project is not None and not rec.project.generic:
            owner = rec.project.owner
            if owner is not None:
                # remove any SubmissionRole instances which have the owner as supervisor
                rec.roles.filter(SubmissionRole.role == SubmissionRole.ROLE_SUPERVISOR, SubmissionRole.user_id == owner.id).delete()

        lp = sel.liveproject
        rec.project_id = lp.id

        if not lp.generic:
            new_owner = lp.owner
            if new_owner is not None:
                role = SubmissionRole(
                    submission_id=rec.id,
                    user_id=new_owner.id,
                    role=SubmissionRole.ROLE_SUPERVISOR,
                    creator_id=current_user.id,
                    creation_timestamp=datetime.now(),
                    last_edit_id=None,
                    last_edit_timestamp=None,
                )
                db.session.add(role)

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not assign project because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@convenor.route("/assign_liveproject/<int:id>/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def assign_liveproject(id, pid):
    # id is a SubmissionRecord
    rec: SubmissionRecord = SubmissionRecord.query.get_or_404(id)

    # find the ProjectClassConfig from which we will draw the list of available LiveProjects
    # (this could be the current one or a previous one, depending on when the student selected, and whether
    # selection occurs in a previous cycle)
    select_config = rec.selector_config
    if select_config is None:
        flash("Can not reassign because the list of available Live Projects could not be found", "error")
        return redirect(redirect_url())

    if not validate_is_convenor(select_config.project_class):
        return redirect(redirect_url())

    if rec.period.is_feedback_open:
        flash("Can not reassign for {name} because feedback is already open".format(name=rec.period.display_name), "error")
        return redirect(redirect_url())

    if rec.student_engaged and rec.project_id is not None:
        flash("Can not reassign for {name} because the project is already marked as started".format(name=rec.period.display_name), "error")
        return redirect(redirect_url())

    lp = LiveProject.query.get_or_404(pid)

    if lp.config_id != select_config.id:
        flash(
            "Can not assign LiveProject #{num} for {name} because they do not belong to the same academic "
            "cycle.".format(num=lp.number, name=rec.period.display_name),
            "error",
        )
        return redirect(redirect_url())

    try:
        # remove any SubmissionRole instances which have the owner as supervisor
        if rec.project is not None and not rec.project.generic:
            owner = rec.project.owner
            if owner is not None:
                # remove any SubmissionRole instances which have the owner as supervisor
                rec.roles.filter(SubmissionRole.role == SubmissionRole.ROLE_SUPERVISOR, SubmissionRole.user_id == owner.id).delete()

        rec.project_id = lp.id

        if not lp.generic:
            new_owner = lp.owner
            if new_owner is not None:
                role = SubmissionRole(
                    submission_id=rec.id,
                    user_id=new_owner.id,
                    role=SubmissionRole.ROLE_SUPERVISOR,
                    creator_id=current_user.id,
                    creation_timestamp=datetime.now(),
                    last_edit_id=None,
                    last_edit_timestamp=None,
                )
                db.session.add(role)

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not assign project because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@convenor.route("/deassign_project/<int:id>")
@roles_accepted("faculty", "admin", "root")
def deassign_project(id):
    # id is a SubmissionRecord
    rec: SubmissionRecord = SubmissionRecord.query.get_or_404(id)

    # find the ProjectClassConfig from which we will draw the list of available LiveProjects
    # (this could be the current one or a previous one, depending on when the student selected, and whether
    # selection occurs in a previous cycle)
    select_config = rec.selector_config
    if select_config is None:
        flash("Can not reassign because the list of available Live Projects could not be found", "error")
        return redirect(redirect_url())

    if not validate_is_convenor(select_config.project_class):
        return redirect(redirect_url())

    if rec.period.is_feedback_open:
        flash("Can not de-assign project for {name} because feedback is already open".format(name=rec.period.display_name), "error")
        return redirect(redirect_url())

    if rec.student_engaged:
        flash("Can not de-assign project for {name} because the project is already marked as started".format(name=rec.period.display_name), "error")
        return redirect(redirect_url())

    # as long as we don't set both project and project_id (or marker and marker_id) simultaneously to zero,
    # the before-update listener for SubmissionRecord will invalidate the correct workload cache entries
    try:
        if rec.project is not None and not rec.project.generic:
            owner = rec.project.owner
            if owner is not None:
                # remove any SubmissionRole instances which have the owner as supervisor
                rec.roles.filter(SubmissionRole.role == SubmissionRole.ROLE_SUPERVISOR, SubmissionRole.user_id == owner.id).delete()

        rec.project = None
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not deassign project because of a database error. Please contact a system administrator", "error")

    return redirect(redirect_url())


@convenor.route("/assign_presentation_feedback/<int:id>/", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def assign_presentation_feedback(id):
    # id labels a SubmissionRecord
    talk: SubmissionRecord = SubmissionRecord.query.get_or_404(id)

    if not validate_is_convenor(talk.owner.config.project_class):
        return redirect(redirect_url())

    if not validate_assign_feedback(talk):
        return redirect(redirect_url())

    slot = talk.schedule_slot
    AssignPresentationFeedbackForm = AssignPresentationFeedbackFormFactory(record_id=talk.id, slot_id=slot.id if slot is not None else None)

    form = AssignPresentationFeedbackForm(request.form)

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    if form.validate_on_submit():
        feedback = PresentationFeedback(
            owner_id=talk.id,
            assessor=form.assessor.data,
            positive=form.positive_feedback.data,
            negative=form.improvement_feedback.data,
            submitted=True,
            timestamp=datetime.now(),
        )

        db.session.add(feedback)
        db.session.commit()

        return redirect(url)

    return render_template_context(
        "faculty/dashboard/edit_feedback.html",
        form=form,
        title="Assign presentation feedback",
        unique_id="assign-{id}".format(id=id),
        formtitle="Assign presentation feedback for <strong>{num}</strong>".format(num=talk.owner.student.user.name),
        submit_url=url_for("convenor.assign_presentation_feedback", id=talk.id, url=url),
    )


@convenor.route("/delete_presentation_feedback/<int:id>/", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def delete_presentation_feedback(id):
    # id labels PresentationFeedback record
    feedback: PresentationFeedback = PresentationFeedback.query.get_or_404(id)

    talk = feedback.owner
    if not validate_is_convenor(talk.owner.config.project_class):
        return redirect(redirect_url())

    db.session.delete(feedback)
    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/edit_feedback/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_feedback(id):
    # id is a SubmissionRole instance
    role: SubmissionRole = SubmissionRole.query.get_or_404(id)
    record: SubmissionRecord = role.submission

    if record.retired:
        flash("It is not possible to edit feedback for submissions that have been retired.", "error")
        return redirect(redirect_url())

    # check is convenor for the project's class
    if not validate_is_convenor(record.project.config.project_class):
        return redirect(redirect_url())

    if not record.period.collect_project_feedback:
        flash("This operation is not permitted. Feedback collection has been disabled for this submission period.", "info")
        return redirect(redirect_url())

    period: SubmissionPeriodRecord = record.period
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
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save feedback due to a database error. Please contact a system administrator.", "error")

        return redirect(url)

    else:
        if request.method == "GET":
            form.positive_feedback.data = role.positive_feedback
            form.improvement_feedback.data = role.improvements_feedback

    return render_template_context(
        "faculty/dashboard/edit_feedback.html",
        form=form,
        title="Edit feedback",
        unique_id="role-{id}".format(id=id),
        formtitle='Edit feedback for <i class="fas fa-user-circle"></i> ' "<strong>{name}</strong>".format(name=record.student_identifier["label"]),
        submit_url=url_for("convenor.edit_feedback", id=id, url=url),
        period=period,
        record=role,
        dont_show_warnings=True,
    )


@convenor.route("/submit_feedback/<int:id>")
@roles_accepted("faculty", "admin", "root")
def submit_feedback(id):
    # id is a SubmissionRole instance
    role: SubmissionRole = SubmissionRole.query.get_or_404(id)
    record: SubmissionRecord = role.submission

    if record.retired:
        flash("It is not possible to edit feedback for submissions that have been retired.", "error")
        return redirect(redirect_url())

    # check is convenor for the project's class
    if not validate_is_convenor(record.project.config.project_class):
        return redirect(redirect_url())

    if not record.period.collect_project_feedback:
        flash("This operation is not permitted. Feedback collection has been disabled for this submission period.", "info")
        return redirect(redirect_url())

    period: SubmissionPeriodRecord = record.period

    if not period.is_feedback_open:
        flash("This operation is not permitted. It is not possible to submit before the feedback period has opened.", "warning")
        return redirect(redirect_url())

    if not role.feedback_valid:
        flash(
            "It is not yet possible to submit this feedback because it is incomplete. Please ensure that you "
            "have provided responses for each category.",
            "warning",
        )
        return redirect(redirect_url())

    if role.submitted_feedback:
        return redirect(redirect_url())

    try:
        role.submitted_feedback = True
        role.feedback_timestamp = datetime.now()

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not submit feedback due to a database error. Please contact a system administrator.", "error")

    return redirect(redirect_url())


@convenor.route("/unsubmit_feedback/<int:id>")
@roles_accepted("faculty", "admin", "root")
def unsubmit_feedback(id):
    # id is a SubmissionRole instance
    role: SubmissionRole = SubmissionRole.query.get_or_404(id)
    record: SubmissionRecord = role.submission

    if record.retired:
        flash("It is not possible to edit feedback for submissions that have been retired.", "error")
        return redirect(redirect_url())

    # check is convenor for the project's class
    if not validate_is_convenor(record.project.config.project_class):
        return redirect(redirect_url())

    if not record.period.collect_project_feedback:
        flash("This operation is not permitted. Feedback collection has been disabled for this submission period.", "info")
        return redirect(redirect_url())

    period: SubmissionPeriodRecord = record.period

    if period.closed:
        flash("This operation is not permitted. It is not possible to unsubmit after the feedback period has closed.", "error")
        return redirect(redirect_url())

    try:
        role.submitted_feedback = False
        role.feedback_timestamp = None

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not unsubmit feedback due to a database error. Please contact a system administrator.", "error")

    return redirect(redirect_url())


@convenor.route("/presentation_edit_feedback/<int:feedback_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def presentation_edit_feedback(feedback_id):
    # feedback_id labels a PresentationFeedback instance
    feedback = PresentationFeedback.query.get_or_404(feedback_id)

    talk = feedback.owner
    if not validate_is_convenor(talk.owner.config.project_class):
        return redirect(redirect_url())

    slot = feedback.owner.schedule_slot
    if slot is None:
        flash("Could not edit feedback because the scheduled slot is unset.", "error")
        return redirect(redirect_url())

    if not slot.owner.deployed:
        flash("Can not edit feedback because the schedule containing this slot has not been deployed.", "error")
        return redirect(redirect_url())

    form = PresentationFeedbackForm(request.form)

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    if form.validate_on_submit():
        feedback.positive = form.positive_feedback.data
        feedback.improvement_feedback = form.improvement_feedback.data

        if feedback.submitted:
            feedback.timestamp = datetime.now()

        db.session.commit()

        return redirect(url)

    else:
        if request.method == "GET":
            form.positive_feedback.data = feedback.positive
            form.improvement_feedback.data = feedback.improvement_feedback

    return render_template_context(
        "faculty/dashboard/edit_feedback.html",
        form=form,
        unique_id="pres-{id}".format(id=id),
        title="Edit presentation feedback from {supervisor}".format(supervisor=feedback.assessor.user.name),
        formtitle='Edit presentation feedback from <i class="fas fa-user-circle"></i> '
        "<strong>{supervisor}</strong> "
        'for <i class="fas fa-user-circle"></i> <strong>{name}</strong>'.format(
            supervisor=feedback.assessor.user.name, name=talk.owner.student.user.name
        ),
        submit_url=url_for("convenor.presentation_edit_feedback", feedback_id=feedback_id, url=url),
        assessment=slot.owner.owner,
        dont_show_warnings=True,
    )


@convenor.route("/presentation_submit_feedback/<int:feedback_id>")
@roles_accepted("faculty", "admin", "root")
def presentation_submit_feedback(feedback_id):
    # feedback_id labels a PresentationFeedback instance
    feedback = PresentationFeedback.query.get_or_404(feedback_id)

    talk = feedback.owner
    if not validate_is_convenor(talk.owner.config.project_class):
        return redirect(redirect_url())

    slot = feedback.owner.schedule_slot
    if slot is None:
        flash("Could not edit feedback because the scheduled slot is unset.", "error")
        return redirect(redirect_url())

    if not slot.owner.deployed:
        flash("Can not edit feedback because the schedule containing this slot has not been deployed.", "error")
        return redirect(redirect_url())

    if not talk.is_presentation_assessor_valid(feedback.assessor_id):
        flash("Cannot submit feedback because it is still incomplete.", "error")
        return redirect(redirect_url())

    feedback.submitted = True
    feedback.timestamp = datetime.now()
    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/presentation_unsubmit_feedback/<int:feedback_id>")
@roles_accepted("faculty", "admin", "root")
def presentation_unsubmit_feedback(feedback_id):
    # feedback_id labels a PresentationFeedback instance
    feedback = PresentationFeedback.query.get_or_404(feedback_id)

    talk = feedback.owner
    if not validate_is_convenor(talk.owner.config.project_class):
        return redirect(redirect_url())

    slot = feedback.owner.schedule_slot
    if slot is None:
        flash("Could not edit feedback because the scheduled slot is unset.", "error")
        return redirect(redirect_url())

    if not slot.owner.deployed:
        flash("Can not edit feedback because the schedule containing this slot has not been deployed.", "error")
        return redirect(redirect_url())

    if not slot.owner.owner.is_feedback_open:
        flash("Cannot unsubmit feedback after an assessment has closed.", "error")
        return redirect(redirect_url())

    feedback.submitted = False
    feedback.timestamp = None
    db.session.commit()

    return redirect(redirect_url())


@convenor.route("/edit_response/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_response(id):
    # id identifies a SubmissionRole instance
    role: SubmissionRole = SubmissionRecord.query.get_or_404(id)
    record: SubmissionRecord = role.submission

    if record.retired:
        flash("It is not possible to edit a response to the submitted for submissions that have been retired.", "error")
        return redirect(redirect_url())

    # check is convenor for the project's class
    if not validate_is_convenor(record.project.config.project_class):
        return redirect(redirect_url())

    if not record.student_feedback_submitted:
        flash(
            "This operation is not permitted. "
            "It is not possible to write a response to feedback from the student before "
            "they have submitted it.",
            "info",
        )
        return redirect(redirect_url())

    form = SubmissionRoleResponseForm(request.form)

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    if form.validate_on_submit():
        record.faculty_response = form.feedback.data
        db.session.commit()

        return redirect(url)

    else:
        if request.method == "GET":
            form.feedback.data = record.faculty_response

    return render_template_context(
        "faculty/dashboard/edit_response.html", form=form, record=record, submit_url=url_for("convenor.edit_response", id=id, url=url), url=url
    )


@convenor.route("/submit_response/<int:id>")
@roles_accepted("faculty", "admin", "root")
def submit_response(id):
    # id identifies a SubmissionRole instance
    role: SubmissionRole = SubmissionRecord.query.get_or_404(id)
    record: SubmissionRecord = role.submission

    if record.retired:
        flash("It is not possible to edit a response to the submitted for submissions that have been retired.", "error")
        return redirect(redirect_url())

    # check is convenor for the project's class
    if not validate_is_convenor(record.project.config.project_class):
        return redirect(redirect_url())

    if role.submitted_response:
        return redirect(redirect_url())

    if not record.student_feedback_submitted:
        flash("This operation is not permitted. It is not possible to respond to feedback from the student before they have submitted it.", "info")
        return redirect(redirect_url())

    if not role.response_valid:
        flash("This response cannot be submitted because it is incomplete. Please ensure that you have provided responses for each category.", "info")
        return redirect(redirect_url())

    try:
        role.submitted_response = True
        role.response_timestamp = datetime.now()

        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not submit response due to a database error. Please contact a system administrator.", "error")

    return redirect(redirect_url())


@convenor.route("/push_feedback/<int:id>")
@roles_accepted("faculty", "admin", "root")
def push_feedback(id):
    # id identifies a SubmissionPeriodRecord
    period = SubmissionPeriodRecord.query.get_or_404(id)

    config = period.config
    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    if not period.closed:
        flash("It is only possible to push feedback once the submission period is closed.", "info")
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    email_task = celery.tasks["app.tasks.push_feedback.push_period"]

    email_task.apply_async((id, current_user.id))

    return redirect(redirect_url())


@convenor.route("/update_CATS/<int:config_id>")
@roles_accepted("faculty", "admin", "root")
def update_CATS(config_id):
    # id identifies a ProjectClassConfig
    config = ProjectClassConfig.query.get_or_404(config_id)
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig. Please contact a system administrator.", "error")
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

    if not validate_is_convenor(sel.config.project_class):
        return redirect(redirect_url())

    if sel.config.selector_lifecycle <= ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN:
        flash("Forced conversion of bookmarks can only be performed after student selections are closed.", "info")
        return redirect(redirect_url())

    if sel.has_submitted:
        flash(
            'Cannot force conversion of bookmarks for selector "{name}" because an existing submission ' "exists.".format(name=sel.student.user.name),
            "error",
        )
        return redirect(redirect_url())

    if sel.number_bookmarks < sel.number_choices:
        flash(
            'Cannot force conversion of bookmarks for selector "{name}" because too few bookmarks ' "exist.".format(name=sel.student.user.name),
            "error",
        )
        return redirect(redirect_url())

    store_selection(sel, converted=True, no_submit_IP=True)

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
            flash("Could not update custom CATS values due to a database error. Please contact a system administrator.", "error")
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for("convenor.faculty", id=record.pclass.id))

    return render_template_context("convenor/dashboard/custom_CATS_limits.html", record=record, form=form, user=record.owner.user)


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
        flash("It is no longer possible to edit this submission period because it has been closed.", "info")
        return redirect(redirect_url())

    # reject if period is retired
    if record.retired:
        flash("It is no longer possible to edit this submission period because it has been retired.", "info")
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    state = config.submitter_lifecycle
    deletable = (current_user.has_role("root") or current_user.has_role("admin")) or (
        not record.closed and (state < config.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY)
    )
    return render_template_context(
        "convenor/documents/period_manager.html", record=record, url=url, text=text, state=state, config=config, deletable=deletable
    )


@convenor.route("/delete_period_attachment/<int:aid>")
@roles_accepted("faculty", "admin", "root")
def delete_period_attachment(aid):
    # aid is a PeriodAttachment id
    attachment: PeriodAttachment = PeriodAttachment.query.get_or_404(aid)
    asset: SubmittedAsset = attachment.attachment

    if asset is None:
        flash("Could not delete attachment because of a database error. Please contact a system administrator.", "info")
        return redirect(redirect_url())

    # check user is convenor the project class this attachment belongs to, or has admin/root privileges
    record: SubmissionPeriodRecord = attachment.parent
    if record is None:
        flash("Can not delete this attachment because it is not attached to a submitter.", "info")
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
    action_url = url_for("convenor.perform_delete_period_attachment", aid=aid, url=url, text=text)

    name = attachment.attachment.target_name if attachment.attachment.target_name is not None else attachment.attachment.filename
    message = (
        "<p>Please confirm that you wish to remove the attachment <strong>{name}</strong> for "
        "{period}.</p>"
        "<p>This action cannot be undone.</p>".format(name=name, period=record.display_name)
    )
    submit_label = "Remove attachment"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=title, action_url=action_url, message=message, submit_label=submit_label
    )


@convenor.route("/perform_delete_period_attachment/<int:aid>")
@roles_accepted("faculty", "admin", "root")
def perform_delete_period_attachment(aid):
    # aid is a PeriodAttachment id
    attachment: PeriodAttachment = PeriodAttachment.query.get_or_404(aid)
    asset: SubmittedAsset = attachment.attachment

    if asset is None:
        flash("Could not delete attachment because of a database error. Please contact a system administrator.", "info")
        return redirect(redirect_url())

    # check user is convenor the project class this attachment belongs to, or has admin/root privileges
    record: SubmissionPeriodRecord = attachment.parent
    if record is None:
        flash("Can not delete this attachment because it is not attached to a submitter.", "info")
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
        flash("Could not remove attachment from the submission period because of a database error. Please contact a system administrator.", "error")
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url_for("convenor.submission_period_documents", pid=record.id, url=url, text=text))


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
            asset = SubmittedAsset(
                timestamp=datetime.now(), uploaded_id=current_user.id, expiry=None, target_name=form.target_name.data, license=form.license.data
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
                flash("Could not upload attachment due to a database issue. Please contact an administrator.", "error")
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return redirect(url_for("convenor.submission_period_documents", pid=pid, url=url, text=text))

            # generate attachment record
            attachment = PeriodAttachment(
                parent_id=record.id,
                attachment_id=asset.id,
                publish_to_students=form.publish_to_students.data,
                include_marker_emails=form.include_marker_emails.data,
                include_supervisor_emails=form.include_supervisor_emails.data,
                description=form.description.data,
                rank_order=get_count(record.attachments),
            )

            # uploading user has access
            asset.grant_user(current_user)

            # project convenor has access
            # 'office', 'convenor', 'moderator', 'exam_board' and 'external_examiner' roles all have access
            asset.grant_roles(["office", "convenor", "moderator", "exam_board", "external_examiner"])

            # if available to students, any student can download
            if form.publish_to_students.data:
                asset.grant_role("student")

            if form.include_marker_emails.data or form.include_supervisor_emails.data:
                asset.grant_role("faculty")

            try:
                db.session.add(attachment)
                db.session.commit()
            except SQLAlchemyError as e:
                flash("Could not upload attachment due to a database issue. Please contact an administrator.", "error")
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

            flash('Attachment "{file}" was successfully uploaded.'.format(file=attachment_file.filename), "info")

            return redirect(url_for("convenor.submission_period_documents", pid=pid, url=url, text=text))

    else:
        if request.method == "GET":
            form.license.data = current_user.default_license

    return render_template_context("convenor/documents/upload_period_attachment.html", record=record, form=form, url=url, text=text)


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
        flash("Cannot edit this attachment due to a database error. Please contact a system administrator.", "info")
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
            flash("Could not commit edits due to a database issue. Please contact an administrator.", "error")
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url)

    else:
        if request.method == "GET":
            form.license.data = asset.license if asset is not None else None

    return render_template_context(
        "convenor/documents/edit_period_attachment.html", attachment=record, record=period, asset=asset, form=form, url=url, text=text
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
    record: SubmissionPeriodRecord = db.session.query(SubmissionPeriodRecord).filter_by(id=period_id).first()

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


def _get_student_task_container(type, sid):
    if type == STUDENT_TASKS_SELECTOR:
        obj: SelectingStudent = db.session.query(SelectingStudent).filter_by(id=sid).first()
        return obj

    if type == STUDENT_TASKS_SUBMITTER:
        obj: SubmittingStudent = db.session.query(SubmittingStudent).filter_by(id=sid).first()
        return obj

    raise KeyError


@convenor.route("/student_tasks/<int:type>/<int:sid>")
@roles_accepted("faculty", "admin", "root")
def student_tasks(type, sid):
    try:
        obj = _get_student_task_container(type, sid)
    except KeyError as e:
        abort(404)

    config: ProjectClassConfig = obj.config
    student: StudentData = obj.student

    # check user is convenor for this project class, or an administrator
    if not validate_is_convenor(config.project_class, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    status_filter = request.args.get("status_filter")

    if status_filter is None and session.get("convenor_student_tasks_status_filter"):
        status_filter = session["convenor_student_tasks_status_filter"]

    if status_filter is not None and status_filter not in ["default", "overdue", "available", "dropped", "completed"]:
        status_filter = "default"

    if status_filter is not None:
        session["convenor_student_tasks_status_filter"] = status_filter

    blocking_filter = request.args.get("blocking_filter")

    if blocking_filter is None and session.get("convenor_student_tasks_blocking_filter"):
        blocking_filter = session["convenor_student_tasks_blocking_filter"]

    if blocking_filter is not None and blocking_filter not in ["all", "blocking", "not-blocking"]:
        blocking_filter = "all"

    if blocking_filter is not None:
        session["convenor_student_tasks_blocking_filter"] = blocking_filter

    return render_template_context(
        "convenor/tasks/student_tasks.html",
        type=type,
        obj=obj,
        config=config,
        student=student,
        url=url,
        text=text,
        status_filter=status_filter,
        blocking_filter=blocking_filter,
    )


@convenor.route("/student_tasks_ajax/<int:type>/<int:sid>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def student_tasks_ajax(type, sid):
    try:
        obj = _get_student_task_container(type, sid)
    except KeyError:
        abort(404)

    config: ProjectClassConfig = obj.config

    # check user is convenor for this project class, or an administrator
    if not validate_is_convenor(config.project_class, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    status_filter = request.args.get("status_filter", "all")
    blocking_filter = request.args.get("blocking_filter", "all")

    if status_filter == "default":
        base_query = obj.tasks.filter(and_(~ConvenorTask.complete, ~ConvenorTask.dropped))
    elif status_filter == "completed":
        base_query = obj.tasks.filter(~ConvenorTask.dropped)
    elif status_filter == "overdue":
        base_query = obj.overdue_tasks
    elif status_filter == "available":
        base_query = obj.available_tasks
    elif status_filter == "dropped":
        base_query = obj.tasks.filter(ConvenorTask.dropped)
    else:
        base_query = obj.tasks

    if blocking_filter == "blocking":
        base_query = base_query.filter(ConvenorTask.blocking)
    elif blocking_filter == "not-blocking":
        base_query = base_query.filter(~ConvenorTask.blocking)

    # set up columns for server-side processing
    task = {"search": ConvenorTask.description, "order": ConvenorTask.description, "search_collation": "utf8_general_ci"}
    defer_date = {"search": func.date_format(ConvenorTask.defer_date, "%a %d %b %Y %H:%M:%S"), "order": ConvenorTask.defer_date}
    due_date = {"search": func.date_format(ConvenorTask.due_date, "%a %d %b %Y %H:%M:%S"), "order": ConvenorTask.due_date}
    status = {
        "order": literal_column("(NOT(complete OR dropped) * (100*(due_date > CURDATE()) + 50*(defer_date > CURDATE())) + 10*complete + 1*dropped)")
    }

    columns = {"task": task, "defer_date": defer_date, "due_date": due_date, "status": status}

    return_url = url_for("convenor.student_tasks", type=type, sid=sid, url=url, text=text)

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(partial(ajax.convenor.student_task_data, type, sid, return_url))


@convenor.route("/add_student_task/<int:type>/<int:sid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def add_student_task(type, sid):
    try:
        obj = _get_student_task_container(type, sid)
    except KeyError as e:
        abort(404)

    config: ProjectClassConfig = obj.config

    # check user is convenor for this project class, or an administrator
    if not validate_is_convenor(config.project_class, message=True):
        return redirect(redirect_url())

    form = AddConvenorStudentTask(request.form)
    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.student_tasks", type=type, sid=sid)

    if form.validate_on_submit():
        task = obj.TaskObjectFactory(
            description=form.description.data,
            notes=form.notes.data,
            blocking=form.blocking.data,
            complete=form.complete.data,
            dropped=form.dropped.data,
            defer_date=form.defer_date.data,
            due_date=form.due_date.data,
            creator_id=current_user.id,
            creation_timestamp=datetime.now(),
        )

        try:
            obj.tasks.append(task)
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not create new task due to a database error. Please contact a system administrator", "error")

        return redirect(url)

    return render_template_context("convenor/tasks/edit_task.html", form=form, url=url, type=type, obj=obj)


@convenor.route("/edit_student_task/<int:tid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_student_task(tid):
    task = db.session.query(with_polymorphic(ConvenorTask, [ConvenorSelectorTask, ConvenorSubmitterTask])).filter_by(id=tid).first()
    if task is None:
        abort(404)

    obj = task.parent
    config: ProjectClassConfig = obj.config

    # check user is convenor for this project class, or an administrator
    if not validate_is_convenor(config.project_class, message=True):
        return redirect(redirect_url())

    form = EditConvenorStudentTask(obj=task)
    url = request.args.get("url", None)
    if url is None:
        url = url_for("convenor.student_tasks", type=obj.polymorphic_identity(), sid=obj.id)

    if form.validate_on_submit():
        task.description = form.description.data
        task.notes = form.notes.data
        task.blocking = form.blocking.data
        task.complete = form.complete.data
        task.dropped = form.dropped.data
        task.defer_date = form.defer_date.data
        task.due_date = form.due_date.data
        task.last_edit_id = current_user.id
        task.last_edit_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes to task due to a database error. Please contact a system administrator", "error")

        return redirect(url)

    return render_template_context("convenor/tasks/edit_task.html", form=form, url=url, obj=obj, task=task)


@convenor.route("/delete_task/<int:tid>")
@roles_accepted("faculty", "admin", "root")
def delete_task(tid):
    task_types = with_polymorphic(ConvenorTask, [ConvenorSelectorTask, ConvenorSubmitterTask, ConvenorGenericTask])

    task = db.session.query(task_types).filter_by(id=tid).first()
    if task is None:
        abort(404)

    obj = task.parent
    task_type = task.__mapper_args__["polymorphic_identity"]
    if task_type == 1 or task_type == 2:
        config: ProjectClassConfig = obj.config
    elif task_type == 3:
        config: ProjectClassConfig = obj
    else:
        flash("Error loading polymorphic object in ", "error")
        return redirect(redirect_url())

    # check user is convenor for this project class, or an administrator
    if not validate_is_convenor(config.project_class, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        if task_type == 1 or task_type == 2:
            url = url_for("convenor.student_tasks", type=task_type, sid=obj.id)
        elif task_type == 3:
            url = url_for("convenor.todo_list", id=config.pclass_id)
        else:
            url = home_dashboard_url()

    if task_type == 1 or task_type == 2:
        title = "Delete student task"
        panel_title = 'Delete task for student <i class="fas fa-user-circle"></i> {name}'.format(name=obj.student.user.name)

        message = (
            "<p>Are you sure that you wish to delete the following task for student "
            '<i class="fas fa-user-circle"></i> {name}?</p>'
            "<p><strong>{desc}</strong></p>"
            "<p>This action cannot be undone.</p>".format(name=obj.student.user.name, desc=task.description)
        )

    elif task_type == 3:
        title = "Delete project task"
        panel_title = "Delete project task"

        message = (
            "<p>Are you sure that you wish to delete the following task?</p>"
            "<p><strong>{desc}</strong></p>"
            "<p>This action cannot be undone.</p>".format(desc=task.description)
        )

    else:
        title = "ERROR"
        panel_title = "ERROR"
        message = "<p>This message should not appear. Please contact a aystem administrator.</p>"

    action_url = url_for("convenor.do_delete_task", tid=tid, url=url)
    submit_label = "Delete task"

    return render_template_context(
        "admin/danger_confirm.html", title=title, panel_title=panel_title, action_url=action_url, message=message, submit_label=submit_label
    )


@convenor.route("/do_delete_task/<int:tid>")
@roles_accepted("faculty", "admin", "root")
def do_delete_task(tid):
    task_types = with_polymorphic(ConvenorTask, [ConvenorSelectorTask, ConvenorSubmitterTask, ConvenorGenericTask])

    task = db.session.query(task_types).filter_by(id=tid).first()
    if task is None:
        abort(404)

    obj = task.parent
    task_type = task.__mapper_args__["polymorphic_identity"]
    if task_type == 1 or task_type == 2:
        config: ProjectClassConfig = obj.config
    elif task_type == 3:
        config: ProjectClassConfig = obj
    else:
        flash("Error loading polymorphic object in ", "error")
        return redirect(redirect_url())

    # check user is convenor for this project class, or an administrator
    if not validate_is_convenor(config.project_class, message=True):
        return redirect(redirect_url())

    url = request.args.get("url", None)
    if url is None:
        url = redirect_url()

    try:
        obj.tasks.remove(task)
        db.session.delete(task)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash("Could not delete task due to a database error. Please contact a system administrator.", "error")

    return redirect(url)


@convenor.route("/mark_task_complete/<int:tid>")
@roles_accepted("faculty", "admin", "root")
def mark_task_complete(tid):
    task_types = with_polymorphic(ConvenorTask, [ConvenorSelectorTask, ConvenorSubmitterTask, ConvenorGenericTask])

    task = db.session.query(task_types).filter_by(id=tid).first()
    if task is None:
        abort(404)

    obj = task.parent
    task_type = task.__mapper_args__["polymorphic_identity"]
    if task_type == 1 or task_type == 2:
        config: ProjectClassConfig = obj.config
    elif task_type == 3:
        config: ProjectClassConfig = obj
    else:
        flash("Error loading polymorphic object in ", "error")
        return redirect(redirect_url())

    # check user is convenor for this project class, or an administrator
    if not validate_is_convenor(config.project_class, message=True):
        return redirect(redirect_url())

    action = request.args.get("action", "complete")

    if action == "complete":
        task.complete = True

        if hasattr(task, "repeat") and task.repeat:
            if task.repeat_interval == task.REPEAT_DAILY:
                interval = relativedelta(days=task.repeat_frequency)
            elif task.repeat_interval == task.REPEAT_MONTHLY:
                interval = relativedelta(months=task.repeat_frequency)
            elif task.repeat_interval == task.REPEAT_YEARLY:
                interval = relativedelta(years=task.repeat_frequency)
            else:
                interval = None

            if interval is not None:
                new_task = clone_model(task)
                new_task.complete = False

                if task.repeat_from_due_date:
                    if task.defer_date is not None:
                        new_task.defer_date = task.defer_date + interval
                    if task.due_date is not None:
                        new_task.due_date = task.due_date + interval

                else:
                    now = datetime.now()
                    new_due_date = now + interval

                    if task.defer_date is not None:
                        if task.due_date is not None:
                            diff = task.due_date - task.defer_date
                            new_task.defer_date = new_due_date - diff
                        else:
                            new_task.defer_date = new_due_date

                    if task.due_date is not None:
                        new_task.due_date = new_due_date

                try:
                    obj.tasks.append(new_task)
                    db.session.commit()
                except SQLAlchemyError as e:
                    db.session.rollback()
                    current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                    flash("Could not generate repeat  task due to a database error. Please contact a system administrator.", "error")

    elif action == "active":
        task.complete = False
    else:
        flash('Unknown action parameter "{param}" passed to mark_task_complete(). Please inform an ' "administrator.".format(param=action), "error")

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        flash("Could not change completion status for this convenor task due to a database error. Please contact a system administrator.", "error")

    return redirect(redirect_url())


@convenor.route("/mark_task_dropped/<int:tid>")
@roles_accepted("faculty", "admin", "root")
def mark_task_dropped(tid):
    task_types = with_polymorphic(ConvenorTask, [ConvenorSelectorTask, ConvenorSubmitterTask, ConvenorGenericTask])

    task = db.session.query(task_types).filter_by(id=tid).first()
    if task is None:
        abort(404)

    obj = task.parent
    task_type = task.__mapper_args__["polymorphic_identity"]
    if task_type == 1 or task_type == 2:
        config: ProjectClassConfig = obj.config
    elif task_type == 3:
        config: ProjectClassConfig = obj
    else:
        flash("Error loading polymorphic object in ", "error")
        return redirect(redirect_url())

    # check user is convenor for this project class, or an administrator
    if not validate_is_convenor(config.project_class, message=True):
        return redirect(redirect_url())

    action = request.args.get("action", "complete")

    if action == "drop":
        task.dropped = True
    elif action == "undrop":
        task.dropped = False
    else:
        flash('Unknown action parameter "{param}" passed to mark_task_dropped(). Please inform an ' "administrator.".format(param=action), "error")

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash("Could not change dropped status for this convenor task due to a database error. Please contact a system administrator.", "error")
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


@convenor.route("/inject_liveproject/<int:pid>/<int:pclass_id>/<int:type>")
@roles_accepted("faculty", "admin", "root")
def inject_liveproject(pid, pclass_id, type):
    project: Project = Project.query.get_or_404(pid)
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    if type not in [1, 2]:
        flash('Could not handle request to attach LiveProject of unknown type "{type}". ' "Please contact a system administrator.".format(type=type))
        return redirect(redirect_url())

    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            'Could not attach LiveProject "{proj}" into project classs "{pcl}" because the '
            "current configuration record could not be "
            "found".format(proj=project.name, pcl=config.name),
            "info",
        )
        return redirect(redirect_url())

    # check user is convenor for this project class, or an administrator
    if not validate_is_convenor(config.project_class, message=True):
        return redirect(redirect_url())

    # check project is available for this project class
    if config.project_class not in project.project_classes:
        flash(
            'Could not attach LiveProject "{proj}" into project class "{pcl}" because this project '
            "is not attached to that class.".format(proj=project.name, pcl=config.name),
            "info",
        )
        return redirect(redirect_url())

    # check a counterpart LiveProject does not already exist
    if config.select_in_previous_cycle:
        if type == 1:
            inject_config = config
        elif type == 2:
            inject_config = config.previous_config
        else:
            flash("Internal error: unexpected type in convenor.inject_liveproject. Please contact a system administrator", "error")
            return redirect(redirect_url())
    else:
        inject_config = config

    if inject_config is None:
        flash(
            'Could not attach LiveProject for "{proj}" to project class "{pcl}" for '
            "{type} because the prior configuration record does not exist. Please contact a system "
            "administrator".format(proj=project.name, pcl=config.name, type="selectors" if type == 1 else "submitters"),
            "warning",
        )
        return redirect(redirect_url())

    # this logic is a bit confusing
    # we are just checking whether inject_config already has a LiveProject attached for this project instance,
    # whether it is to be used for a selector or submitter.
    # However, that means we have to use Project.selector_live_counterpart(), because this is the one that just
    # uses the raw provided ProjectClassConfig object; Project.submitter_live_counterpart() will adjust to
    # the previous config if ProjectClassConfig.select_in_previous_cycle is set

    # the same applies for yra and yrb
    yra = inject_config.submit_year_a
    yrb = inject_config.submit_year_b

    existing = project.selector_live_counterpart(inject_config)
    if existing is not None:
        flash(
            'Could not attach LiveProject for "{proj}" to project class "{pcl}" for '
            "academic year {yra}-{yrb} because a counterpart LiveProject already "
            "exists.".format(proj=project.name, pcl=config.name, yra=yra, yrb=yrb),
            "info",
        )
        return redirect(redirect_url())

    tk_name = "Manually attach LiveProject"
    tk_description = 'Insert project "{proj}" into project class "{pcl}" for academic year ' "{yra}-{yrb}".format(
        proj=project.name, pcl=config.name, yra=yra, yrb=yrb
    )
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    celery = current_app.extensions["celery"]

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    attach = celery.tasks["app.tasks.go_live.project_golive"]

    number = get_count(inject_config.live_projects) + 1

    seq = chain(init.si(task_id, tk_name), attach.si(number, pid, inject_config.id), final.si(task_id, tk_name, current_user.id)).on_error(
        error.si(task_id, tk_name, current_user.id)
    )
    seq.apply_async(task_id=task_id)

    return redirect(redirect_url())
