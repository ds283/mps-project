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

STUDENT_TASKS_SELECTOR = SelectingStudent.polymorphic_identity()
STUDENT_TASKS_SUBMITTER = SubmittingStudent.polymorphic_identity()


def _get_student_task_container(type, sid):
    if type == STUDENT_TASKS_SELECTOR:
        obj: SelectingStudent = (
            db.session.query(SelectingStudent).filter_by(id=sid).first()
        )
        return obj

    if type == STUDENT_TASKS_SUBMITTER:
        obj: SubmittingStudent = (
            db.session.query(SubmittingStudent).filter_by(id=sid).first()
        )
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

    if status_filter is not None and status_filter not in [
        "default",
        "overdue",
        "available",
        "dropped",
        "completed",
    ]:
        status_filter = "default"

    if status_filter is not None:
        session["convenor_student_tasks_status_filter"] = status_filter

    blocking_filter = request.args.get("blocking_filter")

    if blocking_filter is None and session.get(
            "convenor_student_tasks_blocking_filter"
    ):
        blocking_filter = session["convenor_student_tasks_blocking_filter"]

    if blocking_filter is not None and blocking_filter not in [
        "all",
        "blocking",
        "not-blocking",
    ]:
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
        base_query = obj.tasks.filter(
            and_(~ConvenorTask.complete, ~ConvenorTask.dropped)
        )
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
    task = {
        "search": ConvenorTask.description,
        "order": ConvenorTask.description,
        "search_collation": "utf8_general_ci",
    }
    defer_date = {
        "search": func.date_format(ConvenorTask.defer_date, "%a %d %b %Y %H:%M:%S"),
        "order": ConvenorTask.defer_date,
    }
    due_date = {
        "search": func.date_format(ConvenorTask.due_date, "%a %d %b %Y %H:%M:%S"),
        "order": ConvenorTask.due_date,
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

    return_url = url_for(
        "convenor.student_tasks", type=type, sid=sid, url=url, text=text
    )

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(
            partial(ajax.convenor.student_task_data, type, sid, return_url)
        )


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
            flash(
                "Could not create new task due to a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "convenor/tasks/edit_task.html", form=form, url=url, type=type, obj=obj
    )


@convenor.route("/edit_student_task/<int:tid>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def edit_student_task(tid):
    task = (
        db.session.query(
            with_polymorphic(
                ConvenorTask, [ConvenorSelectorTask, ConvenorSubmitterTask]
            )
        )
        .filter_by(id=tid)
        .first()
    )
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
        url = url_for(
            "convenor.student_tasks", type=obj.polymorphic_identity(), sid=obj.id
        )

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
            flash(
                "Could not save changes to task due to a database error. Please contact a system administrator",
                "error",
            )

        return redirect(url)

    return render_template_context(
        "convenor/tasks/edit_task.html", form=form, url=url, obj=obj, task=task
    )


@convenor.route("/delete_task/<int:tid>")
@roles_accepted("faculty", "admin", "root")
def delete_task(tid):
    task_types = with_polymorphic(
        ConvenorTask, [ConvenorSelectorTask, ConvenorSubmitterTask, ConvenorGenericTask]
    )

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
        panel_title = (
            'Delete task for student <i class="fas fa-user-circle"></i> {name}'.format(
                name=obj.student.user.name
            )
        )

        message = (
            "<p>Are you sure that you wish to delete the following task for student "
            '<i class="fas fa-user-circle"></i> {name}?</p>'
            "<p><strong>{desc}</strong></p>"
            "<p>This action cannot be undone.</p>".format(
                name=obj.student.user.name, desc=task.description
            )
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
        "admin/danger_confirm.html",
        title=title,
        panel_title=panel_title,
        action_url=action_url,
        message=message,
        submit_label=submit_label,
    )


@convenor.route("/do_delete_task/<int:tid>")
@roles_accepted("faculty", "admin", "root")
def do_delete_task(tid):
    task_types = with_polymorphic(
        ConvenorTask, [ConvenorSelectorTask, ConvenorSubmitterTask, ConvenorGenericTask]
    )

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
        flash(
            "Could not delete task due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(url)


@convenor.route("/mark_task_complete/<int:tid>")
@roles_accepted("faculty", "admin", "root")
def mark_task_complete(tid):
    task_types = with_polymorphic(
        ConvenorTask, [ConvenorSelectorTask, ConvenorSubmitterTask, ConvenorGenericTask]
    )

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
                    current_app.logger.exception(
                        "SQLAlchemyError exception", exc_info=e
                    )
                    flash(
                        "Could not generate repeat  task due to a database error. Please contact a system administrator.",
                        "error",
                    )

    elif action == "active":
        task.complete = False
    else:
        flash(
            'Unknown action parameter "{param}" passed to mark_task_complete(). Please inform an '
            "administrator.".format(param=action),
            "error",
        )

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        flash(
            "Could not change completion status for this convenor task due to a database error. Please contact a system administrator.",
            "error",
        )

    return redirect(redirect_url())


@convenor.route("/mark_task_dropped/<int:tid>")
@roles_accepted("faculty", "admin", "root")
def mark_task_dropped(tid):
    task_types = with_polymorphic(
        ConvenorTask, [ConvenorSelectorTask, ConvenorSubmitterTask, ConvenorGenericTask]
    )

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
        flash(
            'Unknown action parameter "{param}" passed to mark_task_dropped(). Please inform an '
            "administrator.".format(param=action),
            "error",
        )

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        flash(
            "Could not change dropped status for this convenor task due to a database error. Please contact a system administrator.",
            "error",
        )
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        db.session.rollback()

    return redirect(redirect_url())


INJECT_CURRENT_CYCLE = 1
INJECT_PREVIOUS_CYCLE = 2


@convenor.route("/inject_liveproject/<int:pid>/<int:pclass_id>/<int:type>")
@roles_accepted("faculty", "admin", "root")
def inject_liveproject(pid, pclass_id, type):
    # differences with manual_attach_project()
    # - manual_attach_project() can only attach projects to the currently selecting configuration. inject_liveproject()
    #   can add a LiveProject instance to a previous cycle, if needed
    # - inject_liveproject() does not insist that selections are live

    # TODO - work out what logic can be consolidated between manual_attach_project() and inject_liveproject()

    project: Project = Project.query.get_or_404(pid)
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)

    if type not in [INJECT_CURRENT_CYCLE, INJECT_PREVIOUS_CYCLE]:
        flash(
            'Could not handle request to attach LiveProject of unknown type "{type}". '
            "Please contact a system administrator.".format(type=type)
        )
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
            'Could not attach LiveProject "{proj}" to project class "{pcl}" because this project '
            "is not attached to that class.".format(proj=project.name, pcl=config.name),
            "info",
        )
        return redirect(redirect_url())

    # CHECK A COUNTERPART LIVEPROJECT DOES NOT ALREADY EXIST

    if config.select_in_previous_cycle:
        if type == INJECT_CURRENT_CYCLE:
            inject_config = config
        elif type == INJECT_PREVIOUS_CYCLE:
            inject_config = config.previous_config
        else:
            flash(
                "Internal error: unexpected type in convenor.inject_liveproject. Please contact a system administrator",
                "error",
            )
            return redirect(redirect_url())
    else:
        inject_config = config

    if inject_config is None:
        flash(
            'Could not attach LiveProject for "{proj}" to project class "{pcl}" for '
            "{type} because the prior configuration record does not exist. Please contact a system "
            "administrator".format(
                proj=project.name,
                pcl=config.name,
                type="selectors" if type == 1 else "submitters",
            ),
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
    tk_description = (
        'Insert project "{proj}" into project class "{pcl}" for academic year '
        "{yra}-{yrb}".format(proj=project.name, pcl=config.name, yra=yra, yrb=yrb)
    )
    task_id = register_task(tk_name, owner=current_user, description=tk_description)

    celery = current_app.extensions["celery"]

    init = celery.tasks["app.tasks.user_launch.mark_user_task_started"]
    final = celery.tasks["app.tasks.user_launch.mark_user_task_ended"]
    error = celery.tasks["app.tasks.user_launch.mark_user_task_failed"]

    attach = celery.tasks["app.tasks.go_live.project_golive"]

    number = get_count(inject_config.live_projects) + 1

    seq = chain(
        init.si(task_id, tk_name),
        attach.si(number, pid, inject_config.id),
        final.si(task_id, tk_name, current_user.id),
    ).on_error(error.si(task_id, tk_name, current_user.id))
    seq.apply_async(task_id=task_id)

    return redirect(redirect_url())
