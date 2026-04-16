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
from typing import Tuple

from flask import (
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_security import current_user, roles_accepted
from sqlalchemy import and_, exists, or_

import app.ajax as ajax
from app.convenor import convenor

from ..database import db
from ..models import (
    EmailTemplate,
    EmailWorkflow,
    EmailWorkflowItem,
    EnrollmentRecord,
    FacultyData,
    FilterRecord,
    Project,
    ProjectClass,
    ProjectClassConfig,
    ProjectDescription,
    ProjectTag,
    ProjectTagGroup,
    SubmissionPeriodRecord,
    Tenant,
    TransferableSkill,
    User,
)
from ..shared.context.convenor_dashboard import (
    get_capacity_data,
    get_convenor_approval_data,
    get_convenor_dashboard_data,
    get_convenor_todo_data,
)
from ..shared.context.global_context import render_template_context
from ..shared.forms.queries import GetWorkflowTemplates
from ..shared.projects import (
    get_filter_list_for_groups_and_skills,
    project_list_SQL_handler,
)
from ..shared.utils import (
    get_convenor_filter_record,
    get_current_year,
    redirect_url,
)
from ..shared.validators import (
    validate_is_convenor,
)
from ..tools import ServerSideInMemoryHandler
from .forms import (
    AttachedFilterFormFactory,
    ChangeDeadlineFormFactory,
    GoLiveFormFactory,
    IssueFacultyConfirmRequestFormFactory,
)

_POPULAR_INTERVAL_MAP = {
    "1h": timedelta(hours=1),
    "12h": timedelta(hours=12),
    "1d": timedelta(days=1),
    "3d": timedelta(days=3),
    "1w": timedelta(weeks=1),
}


@convenor.route("/overview")
@roles_accepted("faculty", "admin", "root")
def overview():
    if current_user.has_role("admin") or current_user.has_role("root"):
        pclasses = db.session.query(ProjectClass).filter_by(active=True).all()
    elif current_user.faculty_data is not None:
        pclasses = current_user.faculty_data.convenor_list
    else:
        pclasses = []

    items = []
    for pclass in pclasses:
        config = pclass.most_recent_config
        if config is None:
            continue
        data = get_convenor_dashboard_data(pclass, config)
        items.append({"pclass": pclass, "config": config, "data": data})

    return render_template_context("convenor/dashboard/overview.html", items=items)


@convenor.route("/status/<int:id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def status(id):
    # get details for project class
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)

    # reject user if not a convenor for this project eu
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

    # inject query factories for template selectors
    pclass_id = pclass.id
    golive_form.faculty_template.query_factory = lambda: GetWorkflowTemplates(
        EmailTemplate.GO_LIVE_FACULTY, pclass_id=pclass_id
    )
    golive_form.selector_template.query_factory = lambda: GetWorkflowTemplates(
        EmailTemplate.GO_LIVE_SELECTOR, pclass_id=pclass_id
    )
    golive_form.convenor_template.query_factory = lambda: GetWorkflowTemplates(
        EmailTemplate.GO_LIVE_CONVENOR, pclass_id=pclass_id
    )
    issue_form.confirm_template.query_factory = lambda: GetWorkflowTemplates(
        EmailTemplate.PROJECT_CONFIRMATION_REQUESTED, pclass_id=pclass_id
    )

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

        # pre-select the default templates
        golive_form.faculty_template.data = EmailTemplate.find_template_(
            EmailTemplate.GO_LIVE_FACULTY, pclass=pclass
        )
        golive_form.selector_template.data = EmailTemplate.find_template_(
            EmailTemplate.GO_LIVE_SELECTOR, pclass=pclass
        )
        golive_form.convenor_template.data = EmailTemplate.find_template_(
            EmailTemplate.GO_LIVE_CONVENOR, pclass=pclass
        )
        issue_form.confirm_template.data = EmailTemplate.find_template_(
            EmailTemplate.PROJECT_CONFIRMATION_REQUESTED, pclass=pclass
        )

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


@convenor.route("/popular_projects_ajax/<int:config_id>")
@roles_accepted("faculty", "admin", "root")
def popular_projects_ajax(config_id):
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(config_id)

    if not validate_is_convenor(config.project_class):
        return jsonify({"error": "Forbidden"}), 403

    interval_key = request.args.get("interval", "3d")
    compare_interval = _POPULAR_INTERVAL_MAP.get(interval_key, timedelta(days=3))

    popular_data = config.most_popular_projects(limit=5, compare_interval=compare_interval)

    tbody_html = render_template(
        "convenor/dashboard/overview_cards/popular_projects_tbody.html",
        popular_data=popular_data,
        config_pclass_id=config.pclass_id,
    )

    return jsonify({
        "tbody": tbody_html,
        "updated_at": datetime.now().strftime("%a %d %b %Y %H:%M:%S"),
        "period": interval_key,
    })


@convenor.route("/comms/<int:id>")
@roles_accepted("faculty", "admin", "root")
def comms(id):
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

    from sqlalchemy import func

    # fetch last 15 EmailWorkflow events for this pclass
    workflows = (
        pclass.workflows.order_by(EmailWorkflow.send_time.desc()).limit(15).all()
    )

    # prepare data for each workflow (similar to email_workflow_data in app/ajax/site/email_workflows.py)
    workflow_data = []
    for w in workflows:
        # Item counts via sub-queries for efficiency
        total = (
            db.session.query(func.count(EmailWorkflowItem.id))
            .filter(EmailWorkflowItem.workflow_id == w.id)
            .scalar()
            or 0
        )
        sent = (
            db.session.query(func.count(EmailWorkflowItem.id))
            .filter(
                EmailWorkflowItem.workflow_id == w.id,
                EmailWorkflowItem.sent_timestamp.isnot(None),
            )
            .scalar()
            or 0
        )
        pending = (
            db.session.query(func.count(EmailWorkflowItem.id))
            .filter(
                EmailWorkflowItem.workflow_id == w.id,
                EmailWorkflowItem.sent_timestamp.is_(None),
            )
            .scalar()
            or 0
        )
        errors = (
            db.session.query(func.count(EmailWorkflowItem.id))
            .filter(
                EmailWorkflowItem.workflow_id == w.id,
                EmailWorkflowItem.error_condition.is_(True),
            )
            .scalar()
            or 0
        )
        item_paused = (
            db.session.query(func.count(EmailWorkflowItem.id))
            .filter(
                EmailWorkflowItem.workflow_id == w.id,
                EmailWorkflowItem.paused.is_(True),
            )
            .scalar()
            or 0
        )

        workflow_data.append(
            {
                "w": w,
                "total": total,
                "sent": sent,
                "pending": pending,
                "errors": errors,
                "item_paused": item_paused,
            }
        )

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/comms.html",
        pane="comms",
        pclass=pclass,
        config=config,
        convenor_data=data,
        workflow_data=workflow_data,
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

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/periods.html",
        pane="overview",
        subpane="periods",
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
    active_filter = request.args.get("active_filter")
    supervisor_filter = request.args.get("supervisor_filter")
    generic_filter = request.args.get("generic_filter")
    atas_filter = request.args.get("atas_filter")
    tag_ids_raw = request.args.get("tag_ids")  # None = absent; "" = explicitly cleared

    if valid_filter is None and session.get("convenor_attached_valid_filter"):
        valid_filter = session["convenor_attached_valid_filter"]
    if valid_filter is not None:
        session["convenor_attached_valid_filter"] = valid_filter

    if active_filter is None and session.get("convenor_attached_active_filter"):
        active_filter = session["convenor_attached_active_filter"]
    if active_filter is not None:
        session["convenor_attached_active_filter"] = active_filter

    if supervisor_filter is None and session.get("convenor_attached_supervisor_filter"):
        supervisor_filter = session["convenor_attached_supervisor_filter"]
    if supervisor_filter is not None:
        session["convenor_attached_supervisor_filter"] = supervisor_filter

    if generic_filter is None and session.get("convenor_attached_generic_filter"):
        generic_filter = session["convenor_attached_generic_filter"]
    if generic_filter is not None:
        session["convenor_attached_generic_filter"] = generic_filter

    if atas_filter is None and session.get("convenor_attached_atas_filter"):
        atas_filter = session["convenor_attached_atas_filter"]
    if atas_filter is not None:
        session["convenor_attached_atas_filter"] = atas_filter

    if tag_ids_raw is None:
        # Parameter absent from URL — restore from session (e.g. navigating via other filter buttons)
        tag_ids_raw = session.get("convenor_attached_tag_ids", "")
    else:
        # Parameter explicitly present (even as "") — save to session (clears it when empty)
        session["convenor_attached_tag_ids"] = tag_ids_raw

    # apply defaults
    if active_filter is None:
        active_filter = "1"
    if supervisor_filter is None:
        supervisor_filter = "1"
    if generic_filter is None:
        generic_filter = "0"
    if atas_filter is None:
        atas_filter = "0"

    # build tag filter form pre-populated with current selection
    tag_ids = [int(x) for x in tag_ids_raw.split(",") if x.strip().isdigit()]
    tag_filter_form = AttachedFilterFormFactory(tenant=pclass.tenant)()
    if tag_ids:
        tag_filter_form.tag_filter.data = (
            db.session.query(ProjectTag)
            .filter(
                ProjectTag.id.in_(tag_ids),
            )
            .all(),
            [],
        )

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
        active_filter=active_filter,
        supervisor_filter=supervisor_filter,
        generic_filter=generic_filter,
        atas_filter=atas_filter,
        tag_ids_raw=tag_ids_raw,
        tag_filter_form=tag_filter_form,
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
    active_filter = request.args.get("active_filter", "1")
    supervisor_filter = request.args.get("supervisor_filter", "1")
    generic_filter = request.args.get("generic_filter", "0")
    atas_filter = request.args.get("atas_filter", "0")
    tag_ids_raw = request.args.get("tag_ids", "")

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

    # active projects only (default ON)
    if active_filter != "0":
        base_query = base_query.filter(Project.active.is_(True))

    # supervisor enrolled filter (default ON) — use correlated EXISTS to avoid join conflicts
    if supervisor_filter != "0":
        supervisor_enrolled = exists().where(
            and_(
                EnrollmentRecord.owner_id == Project.owner_id,
                EnrollmentRecord.pclass_id == pclass.id,
                EnrollmentRecord.supervisor_state
                == EnrollmentRecord.SUPERVISOR_ENROLLED,
            )
        )
        base_query = base_query.filter(
            or_(Project.generic.is_(True), supervisor_enrolled)
        )

    # generic projects only (default OFF)
    if generic_filter == "1":
        base_query = base_query.filter(Project.generic.is_(True))

    # ATAS-restricted projects only (default OFF)
    if atas_filter == "1":
        base_query = base_query.filter(Project.ATAS_restricted.is_(True))

    # tag filter
    tag_ids = [int(x) for x in tag_ids_raw.split(",") if x.strip().isdigit()]
    if tag_ids:
        base_query = base_query.filter(Project.tags.any(ProjectTag.id.in_(tag_ids)))

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
