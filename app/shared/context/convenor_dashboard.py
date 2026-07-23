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

from flask import url_for
from flask_security import current_user
from sqlalchemy import and_, or_
from sqlalchemy.event import listens_for

from ...cache import cache
from ...database import db
from ...models import (
    ConfirmRequest,
    EnrollmentRecord,
    FacultyData,
    MarkingEvent,
    Project,
    ProjectClass,
    ProjectClassConfig,
    ProjectDescription,
    ResearchGroup,
    SelectingStudent,
    SubmissionPeriodRecord,
    SubmittingStudent,
    Tenant,
    Ticket,
    User,
    WorkflowMixin,
)
from ...models.journal import journal_unread_count
from ...models.markingevent import ConvenorAction, ConvenorActionButton
from ..convenor import (
    build_accepted_confirmations_query,
    build_accepted_custom_query,
    build_all_confirmations_query,
    build_all_custom_query,
    build_declined_confirmations_query,
    build_declined_custom_query,
    build_outstanding_confirmations_query,
    build_outstanding_custom_query,
)
from ..sqlalchemy import get_count


def get_convenor_dashboard_data(pclass: ProjectClass, config: ProjectClassConfig):
    """
    Efficiently retrieve statistics needed to render the convenor dashboard
    :param pclass:
    :param config:
    :return:
    """
    all_fac_query = (
        db.session.query(User)
        .filter(
            User.active.is_(True),
            User.tenants.any(Tenant.id == pclass.tenant_id),
        )
        .join(FacultyData, FacultyData.id == User.id)
    )

    all_fac_count = get_count(all_fac_query)
    enrolled_fac_count = get_count(all_fac_query.filter(FacultyData.enrollments.any(pclass_id=pclass.id)))

    attached_projects = (
        db.session.query(Project)
        .filter(Project.active.is_(True), Project.project_classes.any(id=pclass.id))
        .join(User, User.id == Project.owner_id, isouter=True)
        .join(FacultyData, FacultyData.id == User.id, isouter=True)
        .join(
            EnrollmentRecord,
            EnrollmentRecord.owner_id == Project.owner_id,
            isouter=True,
        )
        .filter(
            or_(
                Project.use_supervisor_pool.is_(True),
                and_(
                    Project.use_supervisor_pool.is_(False),
                    EnrollmentRecord.pclass_id == pclass.id,
                    EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED,
                    FacultyData.id != None,
                    User.active.is_(True),
                ),
            )
        )
    )
    proj_count = get_count(attached_projects)

    sel_count = get_count(config.selecting_students.filter_by(retired=False))
    sub_count = get_count(config.submitting_students.filter_by(retired=False))
    live_count = get_count(config.live_projects)
    missing_canvas_count = get_count(config.missing_canvas_students) if config.canvas_enabled else 0

    all_confirms_q = build_all_confirmations_query(config)
    all_confirms = get_count(all_confirms_q)

    outstanding_confirms_q = build_outstanding_confirmations_query(config)
    outstanding_confirms = get_count(outstanding_confirms_q)

    accepted_confirms_q = build_accepted_confirmations_query(config)
    accepted_confirms = get_count(accepted_confirms_q)

    declined_confirms_q = build_declined_confirmations_query(config)
    declined_confirms = get_count(declined_confirms_q)

    last_confirm: Optional[ConfirmRequest] = outstanding_confirms_q.order_by(ConfirmRequest.request_timestamp).first()
    recent_confirm: Optional[ConfirmRequest] = outstanding_confirms_q.order_by(ConfirmRequest.request_timestamp.desc()).first()

    now = datetime.now()
    if last_confirm is not None:
        age: timedelta = now - last_confirm.request_timestamp
        age_oldest_confirm_request: int = age.days
        time_oldest_confirm_request = last_confirm.request_timestamp
    else:
        age_oldest_confirm_request = None
        time_oldest_confirm_request = None

    if recent_confirm is not None:
        age: timedelta = now - recent_confirm.request_timestamp
        age_recent_confirm_request: int = age.days
        time_recent_confirm_request = recent_confirm.request_timestamp
    else:
        age_recent_confirm_request = None
        time_recent_confirm_request = None

    all_custom_q = build_all_custom_query(config)
    all_custom = get_count(all_custom_q)

    outstanding_custom_q = build_outstanding_custom_query(config)
    outstanding_custom = get_count(outstanding_custom_q)

    accepted_custom_q = build_accepted_custom_query(config)
    accepted_custom = get_count(accepted_custom_q)

    declined_custom_q = build_declined_custom_query(config)
    declined_custom = get_count(declined_custom_q)

    # Count marking events from closed submission periods
    marking_events_count = get_count(
        db.session.query(MarkingEvent)
        .join(SubmissionPeriodRecord, SubmissionPeriodRecord.id == MarkingEvent.period_id)
        .filter(
            and_(
                SubmissionPeriodRecord.config.has(pclass_id=pclass.id),
                SubmissionPeriodRecord.closed == True,
            )
        )
    )

    marking_urgent_count = sum(event.urgent_action_count for period in config.periods for event in period.marking_events)

    config_student_ids = set(
        sid
        for (sid,) in db.session.query(SelectingStudent.student_id).filter(
            SelectingStudent.config_id == config.id, SelectingStudent.retired.is_(False)
        )
    )
    config_student_ids.update(
        sid
        for (sid,) in db.session.query(SubmittingStudent.student_id).filter(
            SubmittingStudent.config_id == config.id, SubmittingStudent.retired.is_(False)
        )
    )
    journal_unread = journal_unread_count(current_user, config_student_ids)

    # ticket counts for this class: open (non-closed) tickets in scope, and the needs-triage
    # subset (unassigned tickets whose scope spans more than one class)
    open_ticket_query = Ticket.query.filter(
        Ticket.status != Ticket.CLOSED,
        Ticket.scope_classes.any(ProjectClass.id == pclass.id),
    )
    ticket_open_count = get_count(open_ticket_query)
    ticket_triage_count = sum(1 for ticket in open_ticket_query.filter(Ticket.assignee_id.is_(None)).all() if ticket.scope_classes.count() > 1)
    ticket_overdue_count = get_count(open_ticket_query.filter(Ticket.due_date.isnot(None), Ticket.due_date < now))

    return {
        "faculty": enrolled_fac_count,
        "total_faculty": all_fac_count,
        "live_projects": live_count,
        "attached_projects": proj_count,
        "selectors": sel_count,
        "submitters": sub_count,
        "outstanding_confirms": outstanding_confirms,
        "age_oldest_confirm_request": age_oldest_confirm_request,
        "time_oldest_confirm_request": time_oldest_confirm_request,
        "age_recent_confirm_request": age_recent_confirm_request,
        "time_recent_confirm_request": time_recent_confirm_request,
        "confirms_total": all_confirms,
        "confirms_accepted": accepted_confirms,
        "confirms_declined": declined_confirms,
        "outstanding_custom": outstanding_custom,
        "custom_total": all_custom,
        "custom_accepted": accepted_custom,
        "custom_declined": declined_custom,
        "marking_events": marking_events_count,
        "missing_canvas_count": missing_canvas_count,
        "marking_urgent_count": marking_urgent_count,
        "journal_unread": journal_unread,
        "ticket_open_count": ticket_open_count,
        "ticket_triage_count": ticket_triage_count,
        "ticket_overdue_count": ticket_overdue_count,
    }


def get_convenor_action_items(pclass: ProjectClass, config: ProjectClassConfig, convenor_data: dict) -> list:
    """
    Build a prioritised list of action items for the convenor actions panel.
    Takes the already-computed convenor_data dict — does not re-call
    get_convenor_dashboard_data.
    """
    blocking = []
    warnings = []
    advisory = []

    # --- BLOCKING: outstanding confirmation requests >= 14 days old ---
    outstanding = convenor_data.get("outstanding_confirms", 0)
    age_oldest = convenor_data.get("age_oldest_confirm_request")
    if outstanding > 0 and age_oldest is not None and age_oldest >= 14:
        pl = "s" if outstanding != 1 else ""
        blocking.append(
            ConvenorAction(
                severity="blocking",
                icon="hand-paper",
                title=f"{outstanding} outstanding confirmation request{pl} — oldest waiting {int(age_oldest)} days",
                buttons=[
                    ConvenorActionButton(
                        label="View confirmations",
                        url=url_for("convenor.show_confirmations", id=pclass.id),
                        icon="arrow-right",
                    )
                ],
            )
        )

    # --- BLOCKING: MarkingEvents with urgent_action_count > 0 ---
    # Fast exit when the pre-computed aggregate is zero.
    # When non-zero, iterate periods/events to produce one item per affected event.
    if convenor_data.get("marking_urgent_count", 0) > 0:
        for period in config.periods:
            for event in period.marking_events:
                # NOTE: urgent_action_count iterates workflows and submitter_reports
                # per event — O(events × workflows × reports), only reached when > 0.
                n = event.urgent_action_count
                if n > 0:
                    wpl = "s" if n != 1 else ""
                    blocking.append(
                        ConvenorAction(
                            severity="blocking",
                            icon="exclamation-circle",
                            title=f"{event.name} — {n} workflow{wpl} require convenor action",
                            buttons=[
                                ConvenorActionButton(
                                    label="View workflows",
                                    url=url_for(
                                        "convenor.period_marking_events_inspector",
                                        period_id=event.period_id,
                                    ),
                                    icon="arrow-right",
                                )
                            ],
                        )
                    )

    # --- WARNING: open submission periods with submitters awaiting report upload ---
    # Only shown when a marking event is active — if no event is open there is nothing
    # actionable to do about missing reports right now.
    for period in config.periods:
        if not period.closed and period.has_active_marking_event:
            # one query per open period
            n = period.number_submitters_without_reports
            if n > 0:
                spl = "s" if n != 1 else ""
                warnings.append(
                    ConvenorAction(
                        severity="warning",
                        icon="file-upload",
                        title=f"{period.display_name} — {n} submitter{spl} awaiting report upload",
                        buttons=[
                            ConvenorActionButton(
                                label="View submitters",
                                url=url_for("convenor.submitters", id=pclass.id),
                                icon="arrow-right",
                            )
                        ],
                    )
                )

    # --- WARNING: Canvas integration enabled but students not enrolled ---
    missing_canvas = convenor_data.get("missing_canvas_count", 0)
    if missing_canvas > 0:
        spl = "s" if missing_canvas != 1 else ""
        warnings.append(
            ConvenorAction(
                severity="warning",
                icon="chalkboard",
                title=f"{missing_canvas} student{spl} not enrolled in the Canvas module",
                buttons=[
                    ConvenorActionButton(
                        label="View missing students",
                        url=url_for("convenor.submitters", id=pclass.id),
                        icon="arrow-right",
                    )
                ],
            )
        )

    # --- ADVISORY: selectors with no submission and no bookmarks ---
    # NOTE: has_submitted and has_bookmarks are Python properties that run
    # small queries each. This is O(N) for N = active selectors. Acceptable
    # for typical class sizes; could be replaced with a join query if slow.
    inactive = sum(1 for s in config.selecting_students.filter_by(retired=False) if not s.has_submitted and not s.has_bookmarks)
    if inactive > 0:
        spl = "s" if inactive != 1 else ""
        vpl = "have" if inactive != 1 else "has"
        advisory.append(
            ConvenorAction(
                severity="info",
                icon="question-circle",
                title=(f"{inactive} selector{spl} {vpl} neither submitted a selection nor bookmarked any projects — may receive a random allocation"),
                buttons=[
                    ConvenorActionButton(
                        label="View selectors",
                        url=url_for("convenor.selectors", id=pclass.id),
                        icon="arrow-right",
                    )
                ],
            )
        )

    return blocking + warnings + advisory


def get_convenor_open_tickets(config: ProjectClassConfig, limit=10):
    """
    Top open (non-closed) tickets in scope for this config's project class, most-overdue first.
    Feeds the convenor overview dashboard's CTA panel.
    """
    tickets = (
        Ticket.query.filter(
            Ticket.status != Ticket.CLOSED,
            Ticket.scope_classes.any(ProjectClass.id == config.pclass_id),
        )
        .order_by(Ticket.due_date.is_(None), Ticket.due_date)
        .limit(limit)
        .all()
    )

    return {"open_tickets": tickets}


@cache.memoize()
def _compute_group_capacity_data(pclass_id, group_id):
    # filter all 'attached' projects that are tagged with this research group, belonging to active faculty
    # who are normally enrolled
    ps = (
        db.session.query(Project)
        .filter(
            Project.active.is_(True),
            Project.project_classes.any(id=pclass_id),
            Project.group_id == group_id,
        )
        .join(User, User.id == Project.owner_id, isouter=True)
        .join(FacultyData, FacultyData.id == Project.owner_id, isouter=True)
        .join(
            EnrollmentRecord,
            EnrollmentRecord.owner_id == Project.owner_id,
            isouter=True,
        )
        .filter(
            or_(
                Project.use_supervisor_pool.is_(True),
                and_(
                    Project.use_supervisor_pool.is_(False),
                    EnrollmentRecord.pclass_id == pclass_id,
                    EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED,
                    FacultyData.id != None,
                    User.active.is_(True),
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
            if not p.use_supervisor_pool and p.owner is not None:
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
        .filter(FacultyData.affiliations.any(id=group_id), User.active.is_(True))
    )

    # get total number of faculty belonging to this research group
    faculty_in_group = get_count(
        db.session.query(FacultyData.id)
        .join(User, User.id == FacultyData.id)
        .filter(FacultyData.affiliations.any(id=group_id), User.active.is_(True))
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
        .filter(
            Project.active.is_(True),
            Project.project_classes.any(id=pclass_id),
            Project.group_id == group_id,
        )
        .join(User, User.id == Project.owner_id, isouter=True)
        .join(FacultyData, FacultyData.id == Project.owner_id, isouter=True)
        .join(
            EnrollmentRecord,
            EnrollmentRecord.owner_id == Project.owner_id,
            isouter=True,
        )
        .filter(
            or_(
                Project.use_supervisor_pool.is_(True),
                and_(
                    Project.use_supervisor_pool.is_(False),
                    EnrollmentRecord.pclass_id == pclass_id,
                    EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED,
                    FacultyData.id != None,
                    User.active.is_(True),
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

    return {
        "projects": projects,
        "pending": pending,
        "queued": queued,
        "rejected": rejected,
        "approved": approved,
    }


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

    return {
        "data": data,
        "projects": projects,
        "pending": pending,
        "queued": queued,
        "rejected": rejected,
        "approved": approved,
    }


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

    return {
        "data": data,
        "projects": projects,
        "faculty_offering": faculty_offering,
        "capacity": capacity,
        "capacity_bounded": capacity_bounded,
    }
