#
# Created by David Seery on 23/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Read-only view-assembly helpers for the Matching Workspace (see
`.prompts/matching-workspace/PLAN.md`). Every function here takes real ORM instances
(`MatchingAttempt`, `MatchingRecord`, `FacultyData`) and returns a plain dict (or list of dicts)
ready to be handed to a Jinja2 template or JSON-serialised for an AJAX response. None of these
functions render templates, touch `request`, or mutate the database — they only read.

`current_user` is used for viewer-scoped visibility (journal entries), consistent with the
existing `journal_activity_summary`/`batch_journal_counts` helpers in `app/models/journal.py`,
which take the viewing user explicitly for the same reason.
"""

from collections import defaultdict
from typing import Dict, FrozenSet, List, Optional, Tuple

from flask_security import current_user
from sqlalchemy import or_

from .sqlalchemy import get_count
from ..models import (
    EmailLog,
    FacultyData,
    LiveProject,
    MatchingAttempt,
    MatchingRecord,
    MatchingReviewComment,
    MatchingRole,
    SelectionRecord,
    Ticket,
    TicketSubject,
    User,
    batch_journal_counts,
    journal_activity_summary,
)

_SUPERVISOR_ROLES = [MatchingRole.ROLE_SUPERVISOR, MatchingRole.ROLE_RESPONSIBLE_SUPERVISOR]
_MARKER_ROLES = [MatchingRole.ROLE_MARKER]


# ############################
# INTERNAL HELPERS
# ############################


def _role_dict(roles_query, role_ids: List[int]) -> Dict[int, User]:
    """
    Build a {user_id: User} dict from a MatchingRecord.roles/.original_roles dynamic
    relationship, restricted to the given MatchingRole role-type ids.
    """
    return {role.user_id: role.user for role in roles_query.filter(MatchingRole.role.in_(role_ids))}


def _all_roles_set(roles_query) -> FrozenSet[Tuple[int, int]]:
    """
    Build a (role, user_id) pair set from a MatchingRecord.roles/.original_roles dynamic
    relationship, covering every role type. Used only to decide whether *anything* about the
    role assignment has changed; use `_role_dict()` when the role type matters.
    """
    return frozenset((role.role, role.user_id) for role in roles_query)


def _record_is_modified(record: MatchingRecord) -> bool:
    """
    A MatchingRecord counts as modified iff its live project assignment or its live role
    assignment differs from the optimiser baseline (`original_project_id` / `original_roles`).
    """
    if record.project_id != record.original_project_id:
        return True

    return _all_roles_set(record.roles) != _all_roles_set(record.original_roles)


def _rank_band(rank: Optional[int]) -> Optional[str]:
    """
    Severity band for a ranking: 1-2 is a good outcome, 3 is borderline, 4+ is poor.
    Band names are Bootstrap 5.3 semantic tokens (`.claude/rules/template-colours.md`).
    """
    if rank is None:
        return None
    if rank <= 2:
        return "success"
    if rank == 3:
        return "warning"
    return "danger"


def _faculty_project_ids_query(attempt: MatchingAttempt, fac: FacultyData):
    """
    Query of LiveProject instances participating in `attempt` that `fac` offers: projects they
    own directly, plus generic/pool projects for which they are a member of the supervisor pool.
    """
    return attempt.projects.filter(
        or_(
            LiveProject.owner_id == fac.id,
            LiveProject.supervisors.any(FacultyData.id == fac.id),
        )
    )


def _get_project(project_id: Optional[int]) -> Optional[LiveProject]:
    if project_id is None:
        return None
    return LiveProject.query.filter_by(id=project_id).first()


def _worst_severity(constraints: List[dict]) -> Optional[str]:
    severities = {c["severity"] for c in constraints}
    if "danger" in severities:
        return "danger"
    if "warning" in severities:
        return "warning"
    return None


def _group_records_by_pclass(records: List[MatchingRecord]) -> Dict[int, List[dict]]:
    """
    Group a list of MatchingRecords (as returned by MatchingAttempt.get_supervisor_records() /
    .get_marker_records()) by the ProjectClass of the owning selector, building a compact dict
    per record: student, allocated project, and programme-preference match.
    """
    grouped: Dict[int, List[dict]] = defaultdict(list)

    for record in records:
        selector = record.selector
        pclass = selector.config.project_class

        grouped[pclass.id].append(
            {
                "record": record,
                "student": selector.student,
                "project": record.project,
                "programme_pref": record.project.satisfies_preferences(selector) if record.project is not None else None,
            }
        )

    return dict(grouped)


# ############################
# STUDENT TAB
# ############################


def student_row(attempt: MatchingAttempt, record: MatchingRecord) -> dict:
    """
    Assemble the view dict for a single Student-tab row.
    """
    selector = record.selector
    student = selector.student
    project = record.project

    rank = record.total_rank
    journal = batch_journal_counts(current_user, [student.id]).get(student.id, {"visible": 0, "unread": 0})
    open_tickets = get_count(
        Ticket.query.filter(
            Ticket.subjects.any(TicketSubject.selecting_student_id == selector.id),
            Ticket.status.in_(Ticket.OPEN_STATES),
        )
    )

    return {
        "record": record,
        "student": student,
        "user": student.user,
        "pclass": {"instance": selector.config.project_class, "label": selector.config.project_class.make_label()},
        "cohort": student.cohort,
        "programme": student.programme,
        "project": {
            "instance": project,
            "name": project.name if project is not None else None,
            "owner": project.owner.user.name if project is not None and project.owner is not None else None,
        },
        "modified": _record_is_modified(record),
        "programme_pref": project.satisfies_preferences(selector) if project is not None else None,
        "supervisors": record.supervisor_roles,
        "markers": record.marker_roles,
        "rank": rank,
        "rank_band": _rank_band(rank),
        "score": record.current_score,
        "journal": journal,
        "open_tickets": open_tickets,
    }


def student_drawer(attempt: MatchingAttempt, record: MatchingRecord) -> dict:
    """
    Assemble the view dict for the Student inspector drawer: assigned project, quick
    reassignment options (ranked selections with current/original tagging), journal preview,
    open tickets, and recent emails.
    """
    selector = record.selector
    student = selector.student
    user = student.user
    project = record.project

    ranked_selections = []
    for selection in selector.ordered_selections.all():
        selection: SelectionRecord
        ranked_selections.append(
            {
                "selection": selection,
                "project": selection.liveproject,
                "rank": selection.rank,
                "hint": selection.hint,
                "hint_label": SelectionRecord._menu_items.get(selection.hint),
                "is_current": selection.liveproject_id == record.project_id,
                "is_original": selection.liveproject_id == record.original_project_id,
            }
        )

    journal = journal_activity_summary(current_user, [student.id])
    open_tickets = get_count(
        Ticket.query.filter(
            Ticket.subjects.any(TicketSubject.selecting_student_id == selector.id),
            Ticket.status.in_(Ticket.OPEN_STATES),
        )
    )
    recent_emails = user.received_emails.order_by(EmailLog.send_date.desc()).limit(5).all()

    return {
        "record": record,
        "selector": selector,
        "student": student,
        "user": user,
        "project": project,
        "owner": project.owner if project is not None and not project.use_supervisor_pool else None,
        "modified": _record_is_modified(record),
        "ranked_selections": ranked_selections,
        "journal": journal,
        "open_tickets": open_tickets,
        "recent_emails": recent_emails,
    }


# ############################
# FACULTY TAB
# ############################


def faculty_project_ids(attempt: MatchingAttempt, fac: FacultyData) -> FrozenSet[int]:
    """
    Public wrapper over `_faculty_project_ids_query` for callers that only need the id set (e.g.
    validating that a reassignment target project is actually one of `fac`'s), not a full
    row/drawer assembly.
    """
    return frozenset(p.id for p in _faculty_project_ids_query(attempt, fac).all())


def faculty_row(attempt: MatchingAttempt, fac: FacultyData) -> dict:
    """
    Assemble the view dict for a single Faculty-tab row: offered project counts, supervising/
    marking loads grouped by project class, workload CATS, and a binding-constraint severity pill.
    """
    offered_projects = _faculty_project_ids_query(attempt, fac).all()
    offered_by_pclass: Dict[int, int] = defaultdict(int)
    for project in offered_projects:
        offered_by_pclass[project.config.pclass_id] += 1

    supervising_by_pclass = _group_records_by_pclass(attempt.get_supervisor_records(fac.id).all())
    marking_by_pclass = _group_records_by_pclass(attempt.get_marker_records(fac.id).all())

    sup_info = attempt.is_supervisor_overassigned(fac)
    mark_info = attempt.is_marker_overassigned(fac)
    constraints = binding_constraints(attempt, fac)

    return {
        "faculty": fac,
        "offered_by_pclass": dict(offered_by_pclass),
        "offered_total": len(offered_projects),
        "supervising_by_pclass": supervising_by_pclass,
        "marking_by_pclass": marking_by_pclass,
        "workload": {
            "cats_supervising": sup_info["CATS_total"],
            "cats_supervising_limit": sup_info["CATS_limit"],
            "cats_marking": mark_info["CATS_total"],
            "cats_marking_limit": mark_info["CATS_limit"],
            "cats_total": sup_info["CATS_total"] + mark_info["CATS_total"],
        },
        "binding_severity": _worst_severity(constraints),
        "constraints": constraints,
    }


def binding_constraints(attempt: MatchingAttempt, fac: FacultyData) -> List[dict]:
    """
    Normalise CATS-overassignment and project-capacity signals into a flat list of callout
    dicts: {"category", "severity" ("danger"/"warning"), "icon", "text", "project"?}.
    """
    constraints: List[dict] = []

    sup_info = attempt.is_supervisor_overassigned(fac)
    if sup_info["flag"]:
        constraints.append(
            {
                "category": "supervision_cats",
                "severity": "danger",
                "icon": "exclamation-triangle",
                "text": sup_info["error_message"],
            }
        )

    mark_info = attempt.is_marker_overassigned(fac)
    if mark_info["flag"]:
        constraints.append(
            {
                "category": "marking_cats",
                "severity": "danger",
                "icon": "exclamation-triangle",
                "text": mark_info["error_message"],
            }
        )

    for project in _faculty_project_ids_query(attempt, fac).all():
        if not project.enforce_capacity or project.capacity is None:
            continue

        count = attempt.number_project_assignments(project)
        if count > project.capacity:
            constraints.append(
                {
                    "category": "capacity",
                    "severity": "danger",
                    "icon": "ban",
                    "text": f'Project "{project.name}" has capacity {project.capacity} but {count} selectors are currently assigned',
                    "project": project,
                }
            )
        elif count == project.capacity:
            constraints.append(
                {
                    "category": "capacity",
                    "severity": "warning",
                    "icon": "exclamation-circle",
                    "text": f'Project "{project.name}" is at full capacity ({count}/{project.capacity})',
                    "project": project,
                }
            )

    return constraints


def faculty_drawer(attempt: MatchingAttempt, fac: FacultyData) -> dict:
    """
    Assemble the view dict for the Faculty inspector drawer: workload bars, binding-constraint
    callouts, offered projects with capacity/allocation detail, and the assignable pool.
    """
    sup_info = attempt.is_supervisor_overassigned(fac)
    mark_info = attempt.is_marker_overassigned(fac)

    projects = []
    for project in _faculty_project_ids_query(attempt, fac).all():
        assigned_records = attempt.records.filter_by(project_id=project.id).all()
        projects.append(
            {
                "project": project,
                "capacity": project.capacity,
                "enforce_capacity": project.enforce_capacity,
                "assigned_count": attempt.number_project_assignments(project),
                "assigned_students": [record.selector.student for record in assigned_records],
            }
        )

    return {
        "faculty": fac,
        "workload": {
            "cats_supervising": sup_info["CATS_total"],
            "cats_supervising_limit": sup_info["CATS_limit"],
            "cats_marking": mark_info["CATS_total"],
            "cats_marking_limit": mark_info["CATS_limit"],
            "cats_total": sup_info["CATS_total"] + mark_info["CATS_total"],
        },
        "constraints": binding_constraints(attempt, fac),
        "projects": projects,
        "assignable_pool": faculty_assignable_pool(attempt, fac),
    }


def faculty_assignable_pool(attempt: MatchingAttempt, fac: FacultyData) -> dict:
    """
    Build the three tone-coded, mutually-exclusive candidate lists for reassigning a selector
    onto one of `fac`'s projects:

    - `top_choice_elsewhere`: ranked one of F's projects #1, but currently allocated elsewhere.
    - `would_prefer`: currently allocated elsewhere, but has a better (lower) rank for one of
      F's projects than for their current allocation.
    - `interested`: ranked one of F's projects (at any rank), currently allocated elsewhere, and
      not already covered by the two lists above. Ordered by rank ascending.
    """
    fac_project_ids = {p.id for p in _faculty_project_ids_query(attempt, fac).all()}

    empty = {"top_choice_elsewhere": [], "would_prefer": [], "interested": []}
    if not fac_project_ids:
        return empty

    selector_ids = {s.id for s in attempt.selector_list_query().all()}
    if not selector_ids:
        return empty

    selections = SelectionRecord.query.filter(
        SelectionRecord.liveproject_id.in_(fac_project_ids),
        SelectionRecord.owner_id.in_(selector_ids),
    ).all()

    by_selector: Dict[int, List[SelectionRecord]] = defaultdict(list)
    for selection in selections:
        by_selector[selection.owner_id].append(selection)

    top_choice_elsewhere = []
    would_prefer = []
    interested = []

    for selector_id, sel_list in by_selector.items():
        record: Optional[MatchingRecord] = attempt.records.filter_by(selector_id=selector_id).first()
        if record is None or record.project_id in fac_project_ids:
            # no current allocation to compare against, or already allocated to one of F's projects
            continue

        ranked = [s for s in sel_list if s.rank is not None]
        if not ranked:
            continue

        best = min(ranked, key=lambda s: s.rank)
        current_rank = record.total_rank

        entry = {
            "selector": record.selector,
            "student": record.selector.student,
            "current_project": record.project,
            "current_rank": current_rank,
            "best_selection": best,
            "best_project": best.liveproject,
            "best_rank": best.rank,
        }

        if best.rank == 1:
            top_choice_elsewhere.append(entry)
        elif current_rank is not None and best.rank < current_rank:
            would_prefer.append(entry)
        else:
            interested.append(entry)

    top_choice_elsewhere.sort(key=lambda e: e["student"].user.last_name or "")
    would_prefer.sort(key=lambda e: e["best_rank"])
    interested.sort(key=lambda e: e["best_rank"])

    return {
        "top_choice_elsewhere": top_choice_elsewhere,
        "would_prefer": would_prefer,
        "interested": interested,
    }


# ############################
# CHANGES TAB
# ############################


def changes_data(attempt: MatchingAttempt) -> dict:
    """
    Diff every MatchingRecord's live state against its optimiser baseline (`original_project_id`
    / `original_roles`), field by field. Provenance is attempt-level only (`last_edited_by` /
    `last_edit_timestamp`) — see PLAN.md non-goals for why per-record provenance is out of scope.
    """
    records = attempt.records.order_by(MatchingRecord.selector_id.asc(), MatchingRecord.submission_period.asc()).all()

    rows = []
    distinct_students = set()

    for record in records:
        changes = []

        if record.project_id != record.original_project_id:
            original_project = _get_project(record.original_project_id)
            changes.append(
                {
                    "field": "project",
                    "before": original_project.name if original_project is not None else None,
                    "after": record.project.name if record.project is not None else None,
                }
            )

        sup_live = _role_dict(record.roles, _SUPERVISOR_ROLES)
        sup_orig = _role_dict(record.original_roles, _SUPERVISOR_ROLES)
        if sup_live.keys() != sup_orig.keys():
            changes.append(
                {
                    "field": "supervisor",
                    "before": [u.name for u in sup_orig.values()],
                    "after": [u.name for u in sup_live.values()],
                }
            )

        mark_live = _role_dict(record.roles, _MARKER_ROLES)
        mark_orig = _role_dict(record.original_roles, _MARKER_ROLES)
        if mark_live.keys() != mark_orig.keys():
            changes.append(
                {
                    "field": "marker",
                    "before": [u.name for u in mark_orig.values()],
                    "after": [u.name for u in mark_live.values()],
                }
            )

        if changes:
            distinct_students.add(record.selector_id)
            rows.append(
                {
                    "record": record,
                    "student": record.selector.student if record.selector is not None else None,
                    "changes": changes,
                    "edited_by": attempt.last_edited_by,
                    "edited_at": attempt.last_edit_timestamp,
                }
            )

    return {
        "rows": rows,
        "field_change_count": sum(len(row["changes"]) for row in rows),
        "distinct_student_count": len(distinct_students),
        "score": attempt.score,
        "current_score": attempt.current_score,
    }


def changes_count(attempt: MatchingAttempt) -> int:
    """
    Number of MatchingRecords whose live state differs from the optimiser baseline. Drives the
    Changes-tab pill badge.
    """
    return len(changes_data(attempt)["rows"])


# ############################
# DASHBOARD STATISTICS (on-demand)
# ############################


def dashboard_statistics(attempt: MatchingAttempt) -> dict:
    """
    On-demand statistics bundle for one MatchingAttempt: programme-preference matched/failed,
    convenor-hint satisfied/violated, delta (rank) range, and CATS range. Computed fresh on every
    call — no caching is added here (see PLAN.md non-goals).
    """
    return {
        "prefer_programme_status": attempt.prefer_programme_status,
        "hint_status": attempt.hint_status,
        "delta_max": attempt.delta_max,
        "delta_min": attempt.delta_min,
        "CATS_max": attempt.CATS_max,
        "CATS_min": attempt.CATS_min,
        "score": attempt.score,
        "current_score": attempt.current_score,
    }


# ############################
# REVIEW COMMENTS
# ############################


def _student_name(record: Optional[MatchingRecord]) -> str:
    if record is not None and record.selector is not None and record.selector.student is not None:
        return record.selector.student.user.name
    return "Unknown student"


def _comment_thread(comment: MatchingReviewComment, replies_by_parent: Dict[int, List[MatchingReviewComment]]) -> dict:
    return {
        "comment": comment,
        "replies": [_comment_thread(reply, replies_by_parent) for reply in replies_by_parent.get(comment.id, [])],
    }


def comments_data(attempt: MatchingAttempt) -> dict:
    """
    Assemble the review-comments panel content for one attempt: a Global thread (whole-match
    scope, matching_record_id is None) and a set of By-assignment threads, one per commented-on
    MatchingRecord, sorted by student name. Each thread is a top-level comment nested with its
    one level of replies.
    """
    comments: List[MatchingReviewComment] = attempt.review_comments.order_by(MatchingReviewComment.creation_timestamp.asc()).all()

    replies_by_parent: Dict[int, List[MatchingReviewComment]] = defaultdict(list)
    top_level: List[MatchingReviewComment] = []
    for comment in comments:
        if comment.parent_id is None:
            top_level.append(comment)
        else:
            replies_by_parent[comment.parent_id].append(comment)

    global_threads = [_comment_thread(c, replies_by_parent) for c in top_level if c.matching_record_id is None]

    assignment_top_level: Dict[int, List[MatchingReviewComment]] = defaultdict(list)
    for comment in top_level:
        if comment.matching_record_id is not None:
            assignment_top_level[comment.matching_record_id].append(comment)

    assignments = []
    for record_id, record_comments in assignment_top_level.items():
        record = record_comments[0].matching_record
        assignments.append(
            {
                "record": record,
                "student_name": _student_name(record),
                "threads": [_comment_thread(c, replies_by_parent) for c in record_comments],
            }
        )
    assignments.sort(key=lambda entry: entry["student_name"])

    return {
        "global_threads": global_threads,
        "assignments": assignments,
        "total_count": len(comments),
        "unresolved_count": sum(1 for c in top_level if not c.resolved),
    }


def unresolved_comment_count(attempt: MatchingAttempt) -> int:
    """
    Cheap count of unresolved top-level review-comment threads, for the workspace shell's
    Review-comments button badge. Does not build the full nested thread structure.
    """
    return attempt.review_comments.filter_by(parent_id=None, resolved=False).count()
