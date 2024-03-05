#
# Created by David Seery on 19/01/2024.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import or_, and_, func
from sqlalchemy.event import listens_for
from sqlalchemy.orm import with_polymorphic

from ..convenor import build_outstanding_confirmations_query
from ..sqlalchemy import get_count
from ...cache import cache
from ...database import db
from ...models import (
    User,
    ProjectClass,
    ProjectClassConfig,
    FacultyData,
    Project,
    EnrollmentRecord,
    SelectingStudent,
    SubmittingStudent,
    ConvenorSelectorTask,
    ConvenorSubmitterTask,
    ConvenorGenericTask,
    ConvenorTask,
    WorkflowMixin,
    ProjectDescription,
    ResearchGroup,
    ConfirmRequest,
)


def get_convenor_dashboard_data(pclass: ProjectClass, config: ProjectClassConfig):
    """
    Efficiently retrieve statistics needed to render the convenor dashboard
    :param pclass:
    :param config:
    :return:
    """
    all_fac_query = db.session.query(User).filter_by(active=True).join(FacultyData, FacultyData.id == User.id)

    all_fac_count = get_count(all_fac_query)
    enrolled_fac_count = get_count(all_fac_query.filter(FacultyData.enrollments.any(pclass_id=pclass.id)))

    attached_projects = (
        db.session.query(Project)
        .filter(Project.active == True, Project.project_classes.any(id=pclass.id))
        .join(User, User.id == Project.owner_id, isouter=True)
        .join(FacultyData, FacultyData.id == User.id, isouter=True)
        .join(EnrollmentRecord, EnrollmentRecord.owner_id == Project.owner_id, isouter=True)
        .filter(
            or_(
                Project.generic == True,
                and_(
                    Project.generic == False,
                    EnrollmentRecord.pclass_id == pclass.id,
                    EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED,
                    FacultyData.id != None,
                    User.active == True,
                ),
            )
        )
    )
    proj_count = get_count(attached_projects)

    sel_count = get_count(config.selecting_students.filter_by(retired=False))
    sub_count = get_count(config.submitting_students.filter_by(retired=False))
    live_count = get_count(config.live_projects)

    todos = build_convenor_tasks_query(config, status_filter="available", due_date_order=True)
    todo_count = get_count(todos)

    outstanding_confirms = build_outstanding_confirmations_query(config)
    outstanding_confirms_count = get_count(outstanding_confirms)

    last_confirm: Optional[ConfirmRequest] = outstanding_confirms.order_by(ConfirmRequest.request_timestamp).first()
    now = datetime.now()
    if last_confirm is not None:
        age: timedelta = now - last_confirm.request_timestamp
        age_oldest_confirm_request: int = age.days
        time_oldest_confirm_request = last_confirm.request_timestamp
    else:
        age_oldest_confirm_request = None
        time_oldest_confirm_request = None

    return {
        "faculty": enrolled_fac_count,
        "total_faculty": all_fac_count,
        "live_projects": live_count,
        "attached_projects": proj_count,
        "selectors": sel_count,
        "submitters": sub_count,
        "todo_count": todo_count,
        "outstanding_confirms_count": outstanding_confirms_count,
        "age_oldest_confirm_request": age_oldest_confirm_request,
        "time_oldest_confirm_request": time_oldest_confirm_request,
    }


def get_convenor_todo_data(config: ProjectClassConfig, task_limit=10):
    # get list of available tasks (not available != all, even excluding dropped and completed tasks)
    tks = build_convenor_tasks_query(config, status_filter="available", due_date_order=True)

    top_tks = tks.limit(task_limit).all()

    return {"top_to_dos": top_tks}


def build_convenor_tasks_query(config: ProjectClassConfig, status_filter="all", blocking_filter="all", due_date_order=True):
    """
    Return a query that extracts convenor tasks for a particular config instance
    :param blocking_filter:
    :param status_filter:
    :param due_date_order:
    :param config: ProjectClassConfig instance used to locate tasks
    :return: SQLAlchemy query instance
    """

    # subquery to get list of current selectors
    selectors = db.session.query(SelectingStudent.id).filter(~SelectingStudent.retired, SelectingStudent.config_id == config.id).subquery()

    # subquery to get list of current submitters
    submitters = db.session.query(SubmittingStudent.id).filter(~SubmittingStudent.retired, SubmittingStudent.config_id == config.id).subquery()

    # find selector tasks that are linked to one of our current selectors
    sel_tks = (
        db.session.query(ConvenorSelectorTask.id).select_from(selectors).join(ConvenorSelectorTask, ConvenorSelectorTask.owner_id == selectors.c.id)
    )

    # find submitter tasks that are linked to one of our current submitters
    sub_tks = (
        db.session.query(ConvenorSubmitterTask.id)
        .select_from(submitters)
        .join(ConvenorSubmitterTask, ConvenorSubmitterTask.owner_id == submitters.c.id)
    )

    # find ids of tasks linked ot this project class config
    task_tks = db.session.query(ConvenorGenericTask.id).filter(ConvenorGenericTask.owner_id == config.id)

    # join these lists to produce a single list of tasks associated with our current selectors or submitters
    task_ids = sel_tks.union(sub_tks).union(task_tks).subquery()

    # query convenor tasks matching our list.
    # Note the bodge tuple(task_ids.c)[0]. This seems to be the only way to get the right column
    # object from the query.union.union construct; if we have just query.union then specifying a column
    # label works, but with a double union the columns end up with anonymous names. That means we have
    # to select by position.
    convenor_task = with_polymorphic(ConvenorTask, [ConvenorSelectorTask, ConvenorSubmitterTask, ConvenorGenericTask])
    tks = db.session.query(convenor_task).join(task_ids, convenor_task.id == tuple(task_ids.c)[0])

    # if only searching for available tasks, skip those that are complete or dropped.
    # also skip tasks with a defer date that has not yet passed, unless they are blocking
    if status_filter == "default":
        tks = tks.filter(and_(~convenor_task.complete, ~convenor_task.dropped))
    elif status_filter == "completed":
        tks = tks.filter(~convenor_task.dropped)
    elif status_filter == "overdue":
        tks = tks.filter(
            and_(~convenor_task.complete, ~convenor_task.dropped, and_(convenor_task.due_date != None, convenor_task.due_date < func.curdate()))
        )
    elif status_filter == "available":
        tks = tks.filter(
            and_(
                ~convenor_task.complete,
                ~convenor_task.dropped,
                or_(
                    convenor_task.defer_date == None,
                    convenor_task.blocking,
                    and_(convenor_task.defer_date != None, convenor_task.defer_date <= func.curdate()),
                ),
            )
        )
    elif status_filter == "dropped":
        tks = tks.filter(convenor_task.dropped)

    if blocking_filter == "blocking":
        tks = tks.filter(convenor_task.blocking)
    elif blocking_filter == "not-blocking":
        tks = tks.filter(~convenor_task.blocking)

    # if required, order by due date
    # (we don't want to do this for server side processing in DataTables, for instance, since the
    # sort order will be specified separately)
    if due_date_order:
        tks = tks.order_by(convenor_task.due_date)

    return tks


@cache.memoize()
def _compute_group_capacity_data(pclass_id, group_id):
    # filter all 'attached' projects that are tagged with this research group, belonging to active faculty
    # who are normally enrolled
    ps = (
        db.session.query(Project)
        .filter(Project.active == True, Project.project_classes.any(id=pclass_id), Project.group_id == group_id)
        .join(User, User.id == Project.owner_id, isouter=True)
        .join(FacultyData, FacultyData.id == Project.owner_id, isouter=True)
        .join(EnrollmentRecord, EnrollmentRecord.owner_id == Project.owner_id, isouter=True)
        .filter(
            or_(
                Project.generic == True,
                and_(
                    Project.generic == False,
                    EnrollmentRecord.pclass_id == pclass_id,
                    EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED,
                    FacultyData.id != None,
                    User.active == True,
                ),
            )
        )
    )

    # set of faculty members offering projects
    faculty_offering = set()

    # number of offerable projects
    projects = 0
    pending = 0
    approved = 0
    rejected = 0
    queued = 0

    # total capacity of projects
    # the flag 'capacity_bounded' is used to track whether any projects have quota enforcement turned off,
    # and therefore the computed capacity is a lower bound
    capacity = 0
    capacity_bounded = True

    for p in ps:
        if p.is_offerable:
            # increment count of offerable projects
            projects += 1

            # add owner to list of faculty offering projects
            if not p.generic and p.owner is not None:
                faculty_offering.add(p.owner.id)

            # evaluate workflow state for this project
            desc = p.get_description(pclass_id)
            if desc is not None:
                cap = desc.capacity
                if cap is not None and cap > 0:
                    capacity += cap

                if not p.enforce_capacity:
                    capacity_bounded = False

                if not desc.confirmed:
                    pending += 1
                elif desc.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_QUEUED:
                    queued += 1
                elif desc.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_REJECTED:
                    rejected += 1
                elif desc.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_VALIDATED:
                    approved += 1

    # get number of enrolled faculty belonging to this research group
    faculty_enrolled = get_count(
        db.session.query(EnrollmentRecord.id)
        .filter(EnrollmentRecord.pclass_id == pclass_id)
        .join(FacultyData, FacultyData.id == EnrollmentRecord.owner_id)
        .join(User, User.id == EnrollmentRecord.owner_id)
        .filter(FacultyData.affiliations.any(id=group_id), User.active == True)
    )

    # get total number of faculty belonging to this research group
    faculty_in_group = get_count(
        db.session.query(FacultyData.id).join(User, User.id == FacultyData.id).filter(FacultyData.affiliations.any(id=group_id), User.active == True)
    )

    return {
        "projects": projects,
        "pending": pending,
        "queued": queued,
        "rejected": rejected,
        "approved": approved,
        "faculty_offering": len(faculty_offering),
        "faculty_enrolled": faculty_enrolled,
        "faculty_in_group": faculty_in_group,
        "capacity": capacity,
        "capacity_bounded": capacity_bounded,
    }


@cache.memoize()
def _compute_group_approvals_data(pclass_id, group_id):
    # filter all 'attached' projects that are tagged with this research group, belonging to active faculty
    # who are normally enrolled
    ps = (
        db.session.query(Project)
        .filter(Project.active == True, Project.project_classes.any(id=pclass_id), Project.group_id == group_id)
        .join(User, User.id == Project.owner_id, isouter=True)
        .join(FacultyData, FacultyData.id == Project.owner_id, isouter=True)
        .join(EnrollmentRecord, EnrollmentRecord.owner_id == Project.owner_id, isouter=True)
        .filter(
            or_(
                Project.generic == True,
                and_(
                    Project.generic == False,
                    EnrollmentRecord.pclass_id == pclass_id,
                    EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED,
                    FacultyData.id != None,
                    User.active == True,
                ),
            )
        )
    )

    # number of offerable projects in different approval workflow states
    projects = 0
    pending = 0
    approved = 0
    rejected = 0
    queued = 0

    for p in ps:
        p: Project
        if p.is_offerable:
            # increment count of offerable projects
            projects += 1

            # evaluate workflow state for this project
            desc = p.get_description(pclass_id)
            if desc is not None:
                if not desc.confirmed:
                    pending += 1
                elif desc.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_QUEUED:
                    queued += 1
                elif desc.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_REJECTED:
                    rejected += 1
                elif desc.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_VALIDATED:
                    approved += 1

    return {"projects": projects, "pending": pending, "queued": queued, "rejected": rejected, "approved": approved}


def _capacity_delete_ProjectDescription_cache(desc):
    for pcl in desc.project_classes:
        if desc.parent is not None:
            cache.delete_memoized(_compute_group_capacity_data, pcl.id, desc.parent.group_id)
            cache.delete_memoized(_compute_group_approvals_data, pcl.id, desc.parent.group_id)
        else:
            cache.delete_memoized(_compute_group_capacity_data)
            cache.delete_memoized(_compute_group_approvals_data)


@listens_for(ProjectDescription, "before_insert")
def _capacity_ProjectDescription_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_ProjectDescription_cache(target)


@listens_for(ProjectDescription, "before_update")
def _capacity_ProjectDescription_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_ProjectDescription_cache(target)


@listens_for(ProjectDescription, "before_delete")
def _capacity_ProjectDescription_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_ProjectDescription_cache(target)


def _capacity_delete_Project_cache(project):
    for pcl in project.project_classes:
        cache.delete_memoized(_compute_group_capacity_data, pcl.id, project.group_id)
        cache.delete_memoized(_compute_group_approvals_data, pcl.id, project.group_id)


@listens_for(Project, "before_insert")
def _capacity_Project_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_Project_cache(target)


@listens_for(Project, "before_update")
def _capacity_Project_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_Project_cache(target)


@listens_for(Project, "before_delete")
def _capacity_Project_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_Project_cache(target)


def _capacity_delete_EnrollmentRecord_cache(record):
    if record.owner_id is None:
        return

    if record.owner is None:
        owner = db.session.query(FacultyData).filter_by(id=record.owner_id).one()
    else:
        owner = record.owner

    for gp in owner.affiliations.all():
        cache.delete_memoized(_compute_group_capacity_data, record.pclass_id, gp.id)
        cache.delete_memoized(_compute_group_approvals_data, record.pclass_id, gp.id)


@listens_for(EnrollmentRecord, "before_insert")
def _capacity_EnrollmentRecord_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_EnrollmentRecord_cache(target)


@listens_for(EnrollmentRecord, "before_update")
def _capacity_EnrollmentRecord_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_EnrollmentRecord_cache(target)


@listens_for(EnrollmentRecord, "before_delete")
def _capacity_EnrollmentRecord_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_EnrollmentRecord_cache(target)


def _capacity_delete_FacultyData_affiliation_cache(target, value):
    # value is the group that has been added or removed to FacultyData.affiliations
    pclasses = db.session.query(ProjectClass).filter_by(active=True).all()

    for pcl in pclasses:
        cache.delete_memoized(_compute_group_capacity_data, pcl.id, value.id)
        cache.delete_memoized(_compute_group_approvals_data, pcl.id, value.id)


@listens_for(FacultyData.affiliations, "append")
def _capacity_FacultyData_affiliations_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        _capacity_delete_FacultyData_affiliation_cache(target, value)


@listens_for(FacultyData.affiliations, "remove")
def _capacity_FacultyData_affiliations_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        _capacity_delete_FacultyData_affiliation_cache(target, value)


def _capacity_delete_FacultyData_cache(fac_data):
    pclasses = db.session.query(ProjectClass).filter_by(active=True).all()

    for pcl in pclasses:
        for gp in fac_data.affiliations:
            cache.delete_memoized(_compute_group_capacity_data, pcl.id, gp.id)
            cache.delete_memoized(_compute_group_approvals_data, pcl.id, gp.id)


@listens_for(FacultyData, "before_insert")
def _capacity_FacultyData_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_FacultyData_cache(target)


@listens_for(FacultyData, "before_update")
def _capacity_FacultyData_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_FacultyData_cache(target)


@listens_for(FacultyData, "before_delete")
def _capacity_FacultyData_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _capacity_delete_FacultyData_cache(target)


def get_convenor_approval_data(pclass: ProjectClass):
    # get list of research groups
    groups = db.session.query(ResearchGroup).filter_by(active=True).order_by(ResearchGroup.name).all()

    data = []

    projects = 0
    pending = 0
    queued = 0
    rejected = 0
    approved = 0

    for group in groups:
        group_data = _compute_group_approvals_data(pclass.id, group.id)

        # update totals
        projects += group_data["projects"]
        pending += group_data["pending"]
        queued += group_data["queued"]
        rejected += group_data["rejected"]
        approved += group_data["approved"]

        # store data for this research group
        data.append({"label": group.make_label(group.name), "data": group_data})

    # add projects that are not attached to any group
    no_group_data = _compute_group_approvals_data(pclass.id, None)

    projects += no_group_data["projects"]
    pending += no_group_data["pending"]
    queued += no_group_data["queued"]
    rejected += no_group_data["rejected"]
    approved += no_group_data["approved"]

    # store data for this research group
    data.append({"label": "Unaffiliated", "data": no_group_data})

    return {"data": data, "projects": projects, "pending": pending, "queued": queued, "rejected": rejected, "approved": approved}


def get_capacity_data(pclass: ProjectClass):
    # get list of research groups
    groups = db.session.query(ResearchGroup).filter_by(active=True).order_by(ResearchGroup.name).all()

    data = []

    projects = 0

    faculty_offering = 0
    capacity = 0
    capacity_bounded = True

    for group in groups:
        group_data = _compute_group_capacity_data(pclass.id, group.id)

        # update totals
        projects += group_data["projects"]

        faculty_offering += group_data["faculty_offering"]
        capacity += group_data["capacity"]
        capacity_bounded = capacity_bounded and group_data["capacity_bounded"]

        # store data for this research group
        data.append({"label": group.make_label(group.name), "data": group_data})

    # add projects that are not attached to any group
    no_group_data = _compute_group_capacity_data(pclass.id, None)

    # update totals
    projects += no_group_data["projects"]

    faculty_offering += no_group_data["faculty_offering"]
    capacity += no_group_data["capacity"]
    capacity_bounded = capacity_bounded and no_group_data["capacity_bounded"]

    data.append({"label": "Unaffiliated", "data": no_group_data})

    return {"data": data, "projects": projects, "faculty_offering": faculty_offering, "capacity": capacity, "capacity_bounded": capacity_bounded}
