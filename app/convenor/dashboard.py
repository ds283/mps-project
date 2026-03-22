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
from app.convenor import convenor

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
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
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
            submit_label="Change deadline",
            skip_label=None,
            datebox_label="The current deadline for responses is",
        )
    else:
        IssueFacultyConfirmRequestForm = IssueFacultyConfirmRequestFormFactory(
            submit_label="Issue confirmation requests",
            skip_label="Skip confirmation step",
            datebox_label="Deadline",
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

    return_url = url_for("convenor.status", id=id)
    return_text = "convenor dashboard"

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
        return_url=return_url,
        return_text=return_text,
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
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    # get record for current submission period
    period: SubmissionPeriodRecord = config.periods.filter_by(
        submission_period=config.submission_period
    ).first()
    if period is None and config.number_submissions > 0:
        flash(
            "Internal error: could not locate SubmissionPeriodRecord. Please contact a system administrator.",
            "error",
        )
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
                submit_label="Close period",
                include_send_button=False,
                include_test_button=False,
                include_close_button=False,
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
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    # get record for current submission period
    period = config.periods.filter_by(
        submission_period=config.submission_period
    ).first()
    if period is None and config.number_submissions > 0:
        flash(
            "Internal error: could not locate SubmissionPeriodRecord. Please contact a system administrator.",
            "error",
        )
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
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
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
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return jsonify({})

    valid_filter = request.args.get("valid_filter")

    # build list of projects attached to this project class
    base_query = db.session.query(Project).filter(Project.project_classes.any(id=id))

    if (
        valid_filter == "valid"
        or valid_filter == "not-valid"
        or valid_filter == "reject"
        or valid_filter == "pending"
    ):
        if pclass.require_confirm:
            base_query = base_query.join(
                ProjectDescription, ProjectDescription.parent_id == Project.id
            ).filter(ProjectDescription.project_classes.any(id=pclass.id))

            if valid_filter == "pending":
                base_query = base_query.filter(ProjectDescription.confirmed.is_(False))

        if valid_filter == "valid":
            base_query = base_query.filter(
                ProjectDescription.workflow_state
                != ProjectDescription.WORKFLOW_APPROVAL_QUEUED,
                ProjectDescription.workflow_state
                != ProjectDescription.WORKFLOW_APPROVAL_REJECTED,
            )

        if valid_filter == "not-valid":
            base_query = base_query.filter(
                ProjectDescription.workflow_state
                == ProjectDescription.WORKFLOW_APPROVAL_QUEUED
            )

        if valid_filter == "reject":
            base_query = base_query.filter(
                ProjectDescription.workflow_state
                == ProjectDescription.WORKFLOW_APPROVAL_REJECTED
            )

    # restrict query to projects owned by active users, or generic projects
    base_query = base_query.join(
        User, User.id == Project.owner_id, isouter=True
    ).filter(or_(Project.generic.is_(True), User.active.is_(True)))

    # get FilterRecord for currently logged-in user
    filter_record: FilterRecord = get_convenor_filter_record(config)

    valid_group_ids = [g.id for g in filter_record.group_filters]
    valid_skill_ids = [s.id for s in filter_record.skill_filters]

    if pclass.advertise_research_group and len(valid_group_ids) > 0:
        base_query = base_query.filter(Project.group_id.in_(valid_group_ids))

    if len(valid_skill_ids) > 0:
        base_query = base_query.filter(
            Project.skills.any(TransferableSkill.id.in_(valid_skill_ids))
        )

    return project_list_SQL_handler(
        request,
        base_query,
        current_user=current_user,
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

    enrol_filter = request.args.get("enrol_filter")
    state_filter = request.args.get("state_filter")

    if state_filter in ["no-projects", "no-supervisor", "no-marker"]:
        enrol_filter = "enrolled"

    if enrol_filter is None and session.get("convenor_faculty_enroll_filter"):
        enrol_filter = session["convenor_faculty_enroll_filter"]

    if enrol_filter not in [
        "all",
        "enrolled",
        "not-enrolled",
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
        enrol_filter = "all"

    if enrol_filter is not None:
        session["convenor_faculty_enroll_filter"] = enrol_filter

    if state_filter is None and session.get("convenor_faculty_state_filter"):
        state_filter = session["convenor_faculty_state_filter"]

    if state_filter not in [
        "all",
        "no-projects",
        "unofferable",
        "no-supervisor",
        "supervisor-pool",
        "no-marker",
        "custom-cats",
    ]:
        state_filter = "all"

    if state_filter is not None:
        session["convenor_faculty_state_filter"] = state_filter

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

    return render_template_context(
        "convenor/dashboard/faculty.html",
        pane="faculty",
        subpane="list",
        pclass=pclass,
        config=config,
        current_year=current_year,
        faculty=faculty,
        convenor_data=data,
        enrol_filter=enrol_filter,
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

    enrol_filter = request.args.get("enrol_filter")
    state_filter = request.args.get("state_filter")

    # get current configuration record for this project class
    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return jsonify({})

    if enrol_filter == "enrolled":
        # get User, FacultyData pairs for this list
        base_query = (
            db.session.query(User, FacultyData, EnrollmentRecord)
            .filter(
                User.active,
                User.tenants.any(Tenant.id == pclass.tenant_id),
            )
            .join(FacultyData, FacultyData.id == User.id)
            .join(
                EnrollmentRecord,
                and_(
                    EnrollmentRecord.owner_id == FacultyData.id,
                    EnrollmentRecord.pclass_id == pclass.id,
                ),
            )
        )

    elif enrol_filter == "not-enrolled":
        # join to main User and FacultyData records and select pairs that have no counterpart in faculty_ids
        base_query = (
            db.session.query(User, FacultyData, EnrollmentRecord)
            .filter(
                User.active,
                User.tenants.any(Tenant.id == pclass.tenant_id),
            )
            .join(FacultyData, FacultyData.id == User.id)
            .join(
                EnrollmentRecord,
                and_(
                    EnrollmentRecord.owner_id == FacultyData.id,
                    EnrollmentRecord.pclass_id == pclass.id,
                ),
                isouter=True,
            )
            .filter(EnrollmentRecord.id == None)
        )

    elif (
        (
            (
                enrol_filter == "supv-active"
                or enrol_filter == "supv-sabbatical"
                or enrol_filter == "supv-exempt"
            )
            and pclass.uses_supervisor
        )
        or (
            (
                enrol_filter == "mark-active"
                or enrol_filter == "mark-sabbatical"
                or enrol_filter == "mark-exempt"
            )
            and pclass.uses_marker
        )
        or (
            (
                enrol_filter == "pres-active"
                or enrol_filter == "pres-sabbatical"
                or enrol_filter == "pres-exempt"
            )
            and pclass.uses_presentations
        )
    ):
        base_query = (
            db.session.query(User, FacultyData, EnrollmentRecord)
            .filter(
                User.active,
                User.tenants.any(Tenant.id == pclass.tenant_id),
            )
            .join(FacultyData, FacultyData.id == User.id)
            .join(
                EnrollmentRecord,
                and_(
                    EnrollmentRecord.owner_id == FacultyData.id,
                    EnrollmentRecord.pclass_id == pclass.id,
                ),
            )
        )

        if enrol_filter == "supv-active":
            base_query = base_query.filter(
                EnrollmentRecord.supervisor_state
                == EnrollmentRecord.SUPERVISOR_ENROLLED
            )
        elif enrol_filter == "supv-sabbatical":
            base_query = base_query.filter(
                EnrollmentRecord.supervisor_state
                == EnrollmentRecord.SUPERVISOR_SABBATICAL
            )
        elif enrol_filter == "supv-exempt":
            base_query = base_query.filter(
                EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_EXEMPT
            )
        elif enrol_filter == "mark-active":
            base_query = base_query.filter(
                EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_ENROLLED
            )
        elif enrol_filter == "mark-sabbatical":
            base_query = base_query.filter(
                EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_SABBATICAL
            )
        elif enrol_filter == "mark-exempt":
            base_query = base_query.filter(
                EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_EXEMPT
            )
        elif enrol_filter == "pres-active":
            base_query = base_query.filter(
                EnrollmentRecord.presentations_state
                == EnrollmentRecord.PRESENTATIONS_ENROLLED
            )
        elif enrol_filter == "pres-sabbatical":
            base_query = base_query.filter(
                EnrollmentRecord.presentations_state
                == EnrollmentRecord.PRESENTATIONS_SABBATICAL
            )
        elif enrol_filter == "pres-exempt":
            base_query = base_query.filter(
                EnrollmentRecord.presentations_state
                == EnrollmentRecord.PRESENTATIONS_EXEMPT
            )

    else:
        # build list of all active faculty, together with their FacultyData records
        base_query = (
            db.session.query(User, FacultyData, EnrollmentRecord)
            .filter(
                User.active,
                User.tenants.any(Tenant.id == pclass.tenant_id),
            )
            .join(FacultyData, FacultyData.id == User.id)
            .join(
                EnrollmentRecord,
                and_(
                    EnrollmentRecord.owner_id == FacultyData.id,
                    EnrollmentRecord.pclass_id == pclass.id,
                ),
                isouter=True,
            )
        )

    return _faculty_ajax_handler(base_query, pclass, config, state_filter)


def _faculty_ajax_handler(
    base_query, pclass: ProjectClass, config: ProjectClassConfig, state_filter: str
):
    def search_name(row: Tuple[User, FacultyData, EnrollmentRecord]):
        u, fd, er = row
        u: User
        fd: FacultyData
        er: EnrollmentRecord

        return u.name

    def sort_name(row: Tuple[User, FacultyData, EnrollmentRecord]):
        u, fd, er = row
        u: User
        fd: FacultyData
        er: EnrollmentRecord

        return [u.last_name, u.first_name]

    def search_email(row: Tuple[User, FacultyData, EnrollmentRecord]):
        u, fd, er = row
        u: User
        fd: FacultyData
        er: EnrollmentRecord

        return u.email

    def sort_email(row: Tuple[User, FacultyData, EnrollmentRecord]):
        u, fd, er = row
        u: User
        fd: FacultyData
        er: EnrollmentRecord

        return u.email

    def sort_enrolled(row: Tuple[User, FacultyData, EnrollmentRecord]):
        u, fd, er = row
        u: User
        fd: FacultyData
        er: EnrollmentRecord

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

    def sort_golive(row: Tuple[User, FacultyData, EnrollmentRecord]):
        u, fd, er = row
        u: User
        fd: FacultyData
        er: EnrollmentRecord

        return (
            config.require_confirm
            and config.requests_issued
            and config.is_confirmation_required(fd)
        )

    def sort_projects(row: Tuple[User, FacultyData, EnrollmentRecord]):
        u, fd, er = row
        u: User
        fd: FacultyData
        er: EnrollmentRecord

        return fd.number_projects_offered(pclass)

    name = {"search": search_name, "order": sort_name}
    email = {"search": search_email, "order": sort_email}
    enrolled = {"order": sort_enrolled}
    golive = {"order": sort_golive}
    projects = {"order": sort_projects}

    columns = {
        "name": name,
        "email": email,
        "enrolled": enrolled,
        "golive": golive,
        "projects": projects,
    }

    def _filter(state_filter: str, pclass: ProjectClass, row):
        u, fd, er = row
        u: User
        fd: FacultyData
        er: EnrollmentRecord

        if state_filter == "no-projects" and pclass.uses_supervisor:
            return (
                er is not None
                and er.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED
                and fd.number_projects_offered(pclass) == 0
            )

        if state_filter == "no-supervisor" and pclass.uses_supervisor:
            return (
                er is not None
                and er.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED
                and fd.number_projects_supervisable(pclass) == 0
            )

        if state_filter == "supervisor-pool" and pclass.uses_supervisor:
            return fd.number_supervisor_pool(pclass) > 0

        if state_filter == "no-marker" and pclass.uses_marker:
            return (
                er is not None
                and er.marker_state == EnrollmentRecord.SUPERVISOR_ENROLLED
                and fd.number_assessor == 0
            )

        if state_filter == "unofferable":
            return (
                er is not None
                and er.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED
                and fd.projects_unofferable > 0
            )

        if state_filter == "custom-cats":
            return (
                er is not None
                and (
                    er.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED
                    or er.marker_state == EnrollmentRecord.MARKER_ENROLLED
                    or er.moderator_state == EnrollmentRecord.MODERATOR_ENROLLED
                    or er.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED
                )
            ) and _has_custom_CATS(fd, pclass)

        return True

    with ServerSideInMemoryHandler(
        request, base_query, columns, row_filter=partial(_filter, state_filter, pclass)
    ) as handler:
        return handler.build_payload(
            partial(ajax.convenor.faculty_data, pclass, config)
        )


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
