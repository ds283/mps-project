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
                        "to {deadline}.".format(
                            proj=config.name,
                            deadline=config.request_deadline.strftime("%a %d %b %Y"),
                        ),
                        "success",
                    )
                except SQLAlchemyError as e:
                    db.session.rollback()
                    current_app.logger.exception(
                        "SQLAlchemyError exception", exc_info=e
                    )
                    flash(
                        "Could not modify confirmation deadline due to a database error. Please contact a system administrator",
                        "error",
                    )

            # otherwise we need to spawn a background task to issue the confirmation requests
            else:
                # schedule an asynchronous task to issue the requests by email

                # get issue task instance
                celery = current_app.extensions["celery"]
                issue = celery.tasks["app.tasks.issue_confirm.pclass_issue"]
                issue_fail = celery.tasks["app.tasks.issue_confirm.issue_fail"]

                # register as a new background task and push it to the scheduler
                task_id = register_task(
                    'Issue project confirmations for "{proj}" {yra}-{yrb}'.format(
                        proj=config.name, yra=year, yrb=year + 1
                    ),
                    owner=current_user,
                    description='Issue project confirmations for "{proj}"'.format(
                        proj=config.name
                    ),
                )

                if deadline < now:
                    deadline = now + timedelta(weeks=2)

                issue.apply_async(
                    args=(task_id, id, current_user.id, deadline),
                    task_id=task_id,
                    link_error=issue_fail.si(task_id, current_user.id),
                )

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
                flash(
                    "Could not perform skip of confirmation requests due to a dataabase error. Please contact a system administrator",
                    "error",
                )

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

    return render_template_context(
        "convenor/dashboard/outstanding_confirm.html",
        config=config,
        pclass=config.project_class,
    )


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
        config,
        text="list of outstanding confirmations",
        url=url_for("convenor.outstanding_confirm", id=id),
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

    if (
            config.selector_lifecycle
            < ProjectClassConfig.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS
    ):
        flash(
            "Cannot issue reminder emails for this project class because confirmation requests have not yet been generated",
            "info",
        )
        return redirect(redirect_url())

    if (
            config.selector_lifecycle
            > ProjectClassConfig.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS
    ):
        flash(
            "Cannot issue reminder emails for this project class because no further confirmation requests are outstanding",
            "info",
        )
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

    if (
            config.selector_lifecycle
            < ProjectClassConfig.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS
    ):
        flash(
            "Cannot issue reminder emails for this project class because confirmation requests have not yet been generated",
            "info",
        )
        return redirect(redirect_url())

    if (
            config.selector_lifecycle
            > ProjectClassConfig.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS
    ):
        flash(
            "Cannot issue reminder emails for this project class because no further confirmation requests are outstanding",
            "info",
        )
        return redirect(redirect_url())

    celery = current_app.extensions["celery"]
    email_task = celery.tasks["app.tasks.issue_confirm.send_reminder_email"]
    notify_task = celery.tasks["app.tasks.utilities.email_notification"]

    tk = email_task.si(fac_id, config_id) | notify_task.s(
        current_user.id, "Reminder email has been sent", "info"
    )
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

    allowed_tenants = [t.id for t in current_user.tenants]

    base_query = (
        db.session.query(Project)
        .join(User, User.id == Project.owner_id, isouter=True)
        .filter(
            Project.active.is_(True),
            or_(
                Project.generic.is_(True),
                and_(
                    Project.generic.is_(False),
                    User.active.is_(True),
                ),
            ),
        )
    )
    if not current_user.has_role("root"):
        base_query = base_query.filter(
            Project.project_classes.any(ProjectClass.tenant.in_(allowed_tenants)),
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
        current_user=current_user,
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

    # because we filter on supervisor state, this won't confirm projects from any faculty who are bought-out or
    # on sabbatical
    records = db.session.query(EnrollmentRecord).filter_by(
        pclass_id=config.pclass_id,
        supervisor_state=EnrollmentRecord.SUPERVISOR_ENROLLED,
    )

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
            "Please contact a system administrator".format(
                user=fac.user.name, pclass=config.name
            ),
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
                project=config.name,
                yeara=config.submit_year_a,
                yearb=config.submit_year_b,
            ),
            "info",
        )
        return redirect(redirect_url())

    if config.live:
        flash(
            "Confirmation is no longer required for {project} {yeara}-{yearb} because this project "
            "has already gone live".format(
                project=config.name,
                yeara=config.submit_year_a,
                yearb=config.submit_year_b,
            ),
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
            "Please contact a system administrator".format(
                desc=desc.label, proj=desc.parent.name
            ),
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
        flash(
            'A request to Go Live was ignored, because project "{name}" is already '
            "live.".format(name=config.project_class.name),
            "error",
        )
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
            flash(
                "A request to Go Live was ignored because no deadline was entered.",
                "error",
            )
        else:
            return redirect(
                url_for(
                    "convenor.confirm_go_live",
                    id=id,
                    close=int(close),
                    deadline=deadline.isoformat(),
                    notify_faculty=int(notify_faculty),
                    notify_selectors=int(notify_selectors),
                    accommodate_matching=accommodate_matching.id
                    if accommodate_matching is not None
                    else None,
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
        flash(
            'Submitter task "{name}" is blocking {operation}'.format(
                name=task.name, operation=operation
            ),
            "warning",
        )
        flashed_tasks += 1

    if flashed_tasks >= max_tasks_to_flash:
        return

    for task in blocking["selector"]:
        task: ConvenorTask
        if flashed_tasks >= max_tasks_to_flash:
            break
        flash(
            'Selector task "{name}" is blocking {operation}'.format(
                name=task.name, operation=operation
            ),
            "warning",
        )
        flashed_tasks += 1

    if flashed_tasks >= max_tasks_to_flash:
        return

    for task in blocking["global"]:
        task: ConvenorTask
        if flashed_tasks >= max_tasks_to_flash:
            break
        flash(
            'Global project class task "{name}" is blocking {operation}'.format(
                name=task.name, operation=operation
            ),
            "warning",
        )
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
        flash(
            'A request to Go Live was ignored, because project "{name}" is already '
            "live.".format(name=config.project_class.name),
            "error",
        )
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

    title = 'Go Live for "{name}" {yeara}&ndash;{yearb}'.format(
        name=config.project_class.name, yeara=year, yearb=year + 1
    )
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
            name=config.project_class.name,
            yeara=year,
            yearb=year + 1,
            deadline=deadline.strftime("%a %d %b %Y"),
        )
    )
    submit_label = "Go Live"

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
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
        flash(
            'A request to Go Live was ignored, because project "{name}" is already '
            "live.".format(name=config.project_class.name),
            "error",
        )
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
        flash(
            "A request to Go Live was ignored because the deadline was not correctly received",
            "error",
        )
        return redirect(redirect_url())

    deadline = parser.parse(deadline).date()

    year = get_current_year()

    celery = current_app.extensions["celery"]
    golive = celery.tasks["app.tasks.go_live.pclass_golive"]
    golive_fail = celery.tasks["app.tasks.go_live.golive_fail"]
    golive_close = celery.tasks["app.tasks.go_live.golive_close"]

    # register Go Live as a new background task and push it to the celery scheduler
    task_id = register_task(
        'Go Live for "{proj}" {yra}-{yrb}'.format(
            proj=config.name, yra=year, yrb=year + 1
        ),
        owner=current_user,
        description='Perform Go Live of "{proj}"'.format(proj=config.name),
    )

    if close:
        seq = chain(
            golive.si(
                task_id,
                id,
                current_user.id,
                deadline,
                True,
                notify_faculty,
                notify_selectors,
                accommodate_matching,
                full_CATS,
            ),
            golive_close.si(id, current_user.id),
        ).on_error(golive_fail.si(task_id, current_user.id))
        seq.apply_async()

    else:
        golive.apply_async(
            args=(
                task_id,
                id,
                current_user.id,
                deadline,
                False,
                notify_faculty,
                notify_selectors,
                accommodate_matching,
                full_CATS,
            ),
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
            "the deadline has not yet been set for this project class.".format(
                proj=config.name
            ),
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
                    'The deadline for student selections for "{proj}" has been successfully changed to {deadline}.'.format(
                        proj=config.name,
                        deadline=config.live_deadline.strftime("%a %d %b %Y"),
                    ),
                    "success",
                )
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                flash(
                    'Could not adjust selection deadline for "{proj}" due to database error. Please contact a system administrator.'.format(
                        proj=config.name
                    ),
                    "error",
                )

        elif form.close.data:
            notify_convenor = form.notify_convenor.data

            title = f'Close selections for "{config.name}"'
            action_url = url_for(
                "convenor.perform_close_selections",
                configid=configid,
                notify_convenor=int(notify_convenor),
                url=url_for("convenor.status", id=config.pclass_id),
            )
            message = (
                f'<p>Please confirm that you wish to close student selections for project class "{config.name}".</p>'
                "<p>No immediate action is taken, but students will no longer be able to submit ranked preference lists, "
                "and this project class will become available for use when building automated matching attempts.</p>"
            )
            submit_label = "Close selections"

            return render_template_context(
                "admin/danger_confirm.html",
                title=title,
                panel_title=title,
                action_url=action_url,
                message=message,
                submit_label=submit_label,
            )

    return redirect(url_for("convenor.status", id=config.pclass_id))


@convenor.route("/perform_close_selections/<int:configid>")
@roles_accepted("faculty", "admin", "root")
def perform_close_selections(configid):
    # config id is a ProjectClassConfig
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(configid)

    url = request.args.get("url", None)
    if url is None:
        url = redirect(redirect_url())

    notify_convenor = bool(int(request.args.get("notify_convenor", 0)))

    # reject user if not a convenor for this project class
    if not validate_is_convenor(config.project_class):
        return redirect(url)

    # reject if project class not published
    if not validate_project_class(config.project_class):
        return redirect(url)

    # reject if project class is not live
    if not config.live:
        return redirect(redirect_url())

    year = get_current_year()

    celery = current_app.extensions["celery"]
    close = celery.tasks["app.tasks.close_selection.pclass_close"]
    close_fail = celery.tasks["app.tasks.close_selection.close_fail"]

    # register as new background task and push to celery scheduler
    task_id = register_task(
        'Close selections for "{proj}" {yra}-{yrb}'.format(
            proj=config.name, yra=year, yrb=year + 1
        ),
        owner=current_user,
        description='Close selections for "{proj}"'.format(proj=config.name),
    )

    # pclass_close task posts a user message if the close logic proceeds correctly.
    close.apply_async(
        args=(task_id, config.id, current_user.id, notify_convenor),
        task_id=task_id,
        link_error=close_fail.si(task_id, current_user.id),
    )

    return redirect(url)


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
            'The current bookmark list for selector "{name}" is not a valid set of project preferences, and cannot currently be submitted.'.format(
                name=sel.student.user.name
            ),
            "error",
        )
        return redirect(redirect_url())

    try:
        _ = store_selection(sel)
        db.session.commit()

        celery = current_app.extensions["celery"]
        send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]

        msg = EmailTemplate.apply_(
            type=EmailTemplate.STUDENT_NOTIFICATIONS_CHOICES_RECEIVED_PROXY,
            to=[sel.student.user.email, current_user.email],
            reply_to=[current_user.email],
            subject_kwargs={"pcl": sel.config.project_class.name},
            body_kwargs={
                "user": sel.student.user,
                "pclass": sel.config.project_class,
                "config": sel.config,
                "sel": sel,
            },
            pclass=sel.config.project_class,
        )

        # register a new task in the database
        task_id = register_task(
            msg.subject,
            description="Send project choices confirmation email to {r}".format(
                r=", ".join(msg.to)
            ),
        )
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        flash(
            "Project choices for this selector have been successfully stored. A confirmation email has been sent to the selector's registered email address (and copied to you).",
            "info",
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            "A database error occurred during submission. Please contact a system administrator.",
            "error",
        )
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

    if do_confirm(
            sel, project, resolved_by=current_user, comment="Resolved by convenor action"
    ):
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not confirm request because of a database error. Please contact a system administrator",
                "error",
            )

    return redirect(redirect_url())


@convenor.route("/generate_confirm/<int:sid>/<int:pid>")
@roles_accepted("faculty", "admin", "root")
def generate_confirm(sid, pid):
    # sid is a SelectingStudent
    sel: SelectingStudent = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project: LiveProject = LiveProject.query.get_or_404(pid)

    if not validate_is_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_project_open(sel.config):
        return redirect(redirect_url())

    try:
        req = project.make_confirm_request(
            sel,
            state="confirmed",
            resolved_by=current_user,
            comment="Confirmation generated and resolved by convenor",
        )
        db.session.add(req)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not generate confirm request because of a database error. Please contact a system administrator",
            "error",
        )

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
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not change request status to pending because of a database error. Please contact a system administrator",
                "error",
            )

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
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash(
                "Could not cancel confirm request because of a database error. Please contact a system administrator",
                "error",
            )

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
        req.confirm(
            resolved_by=current_user,
            comment="Resolved by convenor 'Project confirm all' action",
        )

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not confirm requests because of a database error. Please contact a system administrator",
            "error",
        )

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
        req.remove(notify_student=True, notify_owner=False)
        db.session.delete(req)

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not delete confirmation requests because of a database error. Please contact a system administrator",
            "error",
        )

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
        req.remove(notify_student=True, notify_owner=False)
        db.session.delete(req)

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not remove confirmations because of a database error. Please contact a system administrator",
            "error",
        )

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

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not change confirmation requests to pending because of a database error. Please contact a system administrator",
            "error",
        )

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
        req.confirm(
            resolved_by=current_user,
            comment="Resolved by convenor 'Student confirm all' action",
        )

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not confirm requests because of a database error. Please contact a system administrator",
            "error",
        )

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
        req.remove(notify_student=True, notify_owner=False)
        db.session.delete(req)

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not remove confirmations because of a database error. Please contact a system administrator",
            "error",
        )

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
        req.remove(notify_student=True, notify_owner=False)
        db.session.delete(req)

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not clear confirmation requests because of a database error. Please contact a system administrator",
            "error",
        )

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

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not change confirmation requests to pending because of a database error. Please contact a system administrator",
            "error",
        )

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

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not change conversion status because of a database error. Please contact a system administrator",
            "error",
        )

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

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash(
            "Could not change conversion status because of a database error. Please contact a system administrator",
            "error",
        )

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

    data = _build_selector_data(
        config,
        cohort_filter,
        prog_filter,
        state_filter,
        convert_filter,
        year_filter,
        match_filter,
        match_show,
    )

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


@convenor.route("/email_project_bookmarkers/<int:project_id>")
@roles_accepted("faculty", "admin", "route")
def email_project_bookmarkers(project_id):
    # project_id identifies a LiveProject
    project: LiveProject = LiveProject.query.get_or_404(project_id)
    config: ProjectClassConfig = project.config

    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    to_list = [item.owner.student.user.id for item in project.bookmarks]

    return redirect(
        url_for(
            "services.send_email",
            url=url_for("convenor.project_bookmarks", id=project_id),
            text="project bookmarks view",
            to=to_list,
        )
    )


@convenor.route("/email_project_selectors/<int:project_id>")
@roles_accepted("faculty", "admin", "route")
def email_project_selectors(project_id):
    # project_id identifies a LiveProject
    project: LiveProject = LiveProject.query.get_or_404(project_id)
    config: ProjectClassConfig = project.config

    if not validate_is_convenor(config.project_class):
        return redirect(redirect_url())

    to_list = [item.owner.student.user.id for item in project.selections]

    return redirect(
        url_for(
            "services.send_email",
            url=url_for("convenor.project_bookmarks", id=project_id),
            text="project bookmarks view",
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

    data = build_submitters_data(
        config, cohort_filter, prog_filter, state_filter, year_filter
    )

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

    data = _build_selector_data(
        config,
        cohort_filter,
        prog_filter,
        state_filter,
        convert_filter,
        year_filter,
        match_filter,
        match_show,
    )

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

    data = _build_selector_data(
        config,
        cohort_filter,
        prog_filter,
        state_filter,
        convert_filter,
        year_filter,
        match_filter,
        match_show,
    )

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
        flash(
            "{name} is not an active project class, and therefore cannot be rolled over.".format(
                name=config.name
            ),
            "error",
        )
        return redirect(redirect_url())

    blocking, num_blocking = config.get_blocking_tasks
    if num_blocking > 0:
        _flash_blocking_tasks("roll-over to next academic year", blocking)
        return redirect(redirect_url())

    title = 'Rollover of "{proj}" to {yeara}&ndash;{yearb}'.format(
        proj=config.name, yeara=year, yearb=year + 1
    )
    action_url = url_for(
        "convenor.rollover", id=id, url=request.referrer, markers=int(use_markers)
    )
    message = (
        '<p>Please confirm that you wish to rollover project class "{proj}" to '
        "{yeara}&ndash;{yearb}.</p>"
        "<p>This action cannot be undone.</p>".format(
            proj=config.name, yeara=year, yearb=year + 1
        )
    )

    if config.select_in_previous_cycle:
        if use_markers:
            submit_label = "Rollover to {yr}".format(yr=year)
        else:
            submit_label = "Rollover to {yr} and drop markers".format(yr=year)
    else:
        submit_label = "Rollover to {yr}".format(yr=year)

    return render_template_context(
        "admin/danger_confirm.html",
        title=title,
        panel_title=title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
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
        flash(
            f'"{config.name}" is not an active project class, and cannot be rolled over.',
            "error",
        )
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
        'Rollover "{proj}" to {yra}-{yrb}'.format(
            proj=config.name, yra=year, yrb=year + 1
        ),
        owner=current_user,
        description='Perform rollover of "{proj}" to new academic year'.format(
            proj=config.name
        ),
    )

    backup_chain = chain(
        backup_msg.si(task_id),
        backup.si(
            current_user.id,
            type=BackupRecord.PROJECT_ROLLOVER_FALLBACK,
            tag="rollover",
            description="Rollback snapshot for {proj} rollover to {yr}".format(
                proj=config.name, yr=year
            ),
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
        args=(task_id, use_markers, id, current_user.id),
        task_id=task_id,
        link_error=rollover_fail.si(task_id, current_user.id),
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
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
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
