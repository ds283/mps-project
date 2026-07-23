#
# Created by David Seery on 21/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Entitlement + candidate-search engine for ticket subjects, shared by the compose flow
(app/tickets/compose.py) and the detail-view "add subject" flow (app/tickets/detail.py).

Three origin cases:

- convenor: reached via a class's convenor ticket ledger. Scope is every SubmittingStudent /
  SelectingStudent anchored on that class's current ProjectClassConfig, plus the class itself.
  Only available when the acting user actually convenes/co-convenes the class.
- faculty: reached via a faculty member's personal inbox. Scope is the classes they actively
  supervise/mark/moderate (active + published only); their non-retired supervisees (supervisor /
  responsible supervisor role), assessees (presentation assessor role) and selectees (via a
  ConfirmRequest onto an owned LiveProject) are shown by name; their non-retired markees/moderatees
  (marker / moderator role) are shown by exam number only, with no avatar and no name-based search,
  to preserve blind-marking anonymity. Exam board / external examiner roles are deliberately
  excluded from scope entirely.
- office (office/admin/root): any non-retired submitting/selecting student, or whole class, in an
  active + published ProjectClassConfig/ProjectClass within the user's current-cycle tenants.
"""

from __future__ import annotations

from typing import Optional

from .scope import home_class
from ...models import (
    ConfirmRequest,
    EnrollmentRecord,
    LiveProject,
    ProjectClass,
    ProjectClassConfig,
    SelectingStudent,
    StudentData,
    SubmissionRecord,
    SubmissionRole,
    SubmittingStudent,
    TicketSubject,
    User,
)
from ...shared.utils import get_current_year

_PREFIX_BY_KIND = {
    TicketSubject.SUBMITTING_STUDENT: "sub",
    TicketSubject.SELECTING_STUDENT: "sel",
    TicketSubject.PROJECT_CLASS: "pc",
}
_KIND_BY_PREFIX = {prefix: kind for kind, prefix in _PREFIX_BY_KIND.items()}
_MODEL_BY_KIND = {
    TicketSubject.SUBMITTING_STUDENT: SubmittingStudent,
    TicketSubject.SELECTING_STUDENT: SelectingStudent,
    TicketSubject.PROJECT_CLASS: ProjectClass,
}

SEARCH_LIMIT = 20


# ------------------------------------------------------------------------------------------------
# token helpers


def token_for(kind, obj_id) -> str:
    return f"{_PREFIX_BY_KIND[kind]}:{obj_id}"


def resolve_token(token: str):
    prefix, _, sid = token.partition(":")
    kind = _KIND_BY_PREFIX.get(prefix)
    if kind is None or not sid.isdigit():
        return None
    obj = _MODEL_BY_KIND[kind].query.get(int(sid))
    if obj is None:
        return None
    return kind, obj


# ------------------------------------------------------------------------------------------------
# role / scope helpers


def is_office_like(user) -> bool:
    return user.has_role("office") or user.has_role("admin") or user.has_role("root")


def user_tenant_ids(user):
    return [tenant.id for tenant in user.tenants]


def target_tenant_id(kind, target) -> Optional[int]:
    if kind == TicketSubject.PROJECT_CLASS:
        return target.tenant_id
    hc = home_class(target)
    return hc.tenant_id if hc is not None else None


def resolve_convenor_pclass(user, pclass_id: Optional[int]):
    """Resolve `pclass_id` to a ProjectClass, but only if `user` convenes/co-convenes it."""
    if pclass_id is None:
        return None

    faculty = getattr(user, "faculty_data", None)
    if faculty is None:
        return None
    convened = {p.id for p in faculty.convenor_for} | {p.id for p in faculty.coconvenor_for}
    if pclass_id not in convened:
        return None

    return ProjectClass.query.get(pclass_id)


def faculty_classes(faculty):
    """Active, published classes a faculty member actively supervises/marks/moderates."""
    classes = {}
    for enrollment in faculty.enrollments:
        pclass = enrollment.pclass
        if pclass is None or not pclass.active or not pclass.publish:
            continue
        if (
            enrollment.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED
            or enrollment.marker_state == EnrollmentRecord.MARKER_ENROLLED
            or enrollment.moderator_state == EnrollmentRecord.MODERATOR_ENROLLED
        ):
            classes[pclass.id] = pclass
    return classes


_SUPERVISOR_ROLES = (SubmissionRole.ROLE_SUPERVISOR, SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR)

# ticket-relevant roles for entitlement purposes; exam board / external examiner are deliberately
# excluded from ticket scope entirely (per spec), not merely displayed differently.
_FACULTY_STUDENT_ROLES = _SUPERVISOR_ROLES + (
    SubmissionRole.ROLE_MARKER,
    SubmissionRole.ROLE_MODERATOR,
    SubmissionRole.ROLE_PRESENTATION_ASSESSOR,
)

# roles relevant to the ticket assign picker's "Related faculty" section (app/tickets/detail.py):
# supervisors, markers and moderators. Presentation assessor is excluded (not ticket-relevant); exam
# board / external examiner roles are not implemented.
_ASSIGNABLE_STUDENT_ROLES = _SUPERVISOR_ROLES + (SubmissionRole.ROLE_MARKER, SubmissionRole.ROLE_MODERATOR)


def _faculty_role_query(user, roles):
    return (
        SubmittingStudent.query.join(SubmissionRecord, SubmissionRecord.owner_id == SubmittingStudent.id)
        .join(SubmissionRole, SubmissionRole.submission_id == SubmissionRecord.id)
        .filter(SubmissionRole.user_id == user.id, SubmissionRole.role.in_(roles), SubmittingStudent.retired.is_(False))
        .distinct()
    )


def faculty_supervisee_query(user):
    """Non-retired SubmittingStudents for which the user holds a supervisor (or responsible
    supervisor) role."""
    return _faculty_role_query(user, _SUPERVISOR_ROLES)


def faculty_marker_query(user):
    """Non-retired SubmittingStudents for which the user holds a marker role. Displayed by exam
    number only (see `_anonymised_role_rows`) to preserve blind-marking anonymity."""
    return _faculty_role_query(user, (SubmissionRole.ROLE_MARKER,))


def faculty_moderator_query(user):
    """Non-retired SubmittingStudents for which the user holds a moderator role. Displayed by exam
    number only (see `_anonymised_role_rows`) to preserve blind-marking anonymity."""
    return _faculty_role_query(user, (SubmissionRole.ROLE_MODERATOR,))


def faculty_assessor_query(user):
    """Non-retired SubmittingStudents for which the user holds a presentation assessor role."""
    return _faculty_role_query(user, (SubmissionRole.ROLE_PRESENTATION_ASSESSOR,))


def faculty_related_student_query(user):
    """Non-retired SubmittingStudents for which the user holds any of the four ticket-relevant
    roles (supervisor, responsible supervisor, marker, moderator, presentation assessor) — used
    for the entitlement check, since a picker candidate offered under any of those roles must also
    be accepted at submit time. Exam board / external examiner roles are deliberately excluded."""
    return _faculty_role_query(user, _FACULTY_STUDENT_ROLES)


def faculty_selectee_query(user):
    """Non-retired SelectingStudents linked, via a ConfirmRequest, to a LiveProject the user owns."""
    faculty = getattr(user, "faculty_data", None)
    if faculty is None:
        return SelectingStudent.query.filter(SelectingStudent.id.is_(None))

    return (
        SelectingStudent.query.join(ConfirmRequest, ConfirmRequest.owner_id == SelectingStudent.id)
        .join(LiveProject, ConfirmRequest.project_id == LiveProject.id)
        .filter(LiveProject.owner_id == faculty.id, SelectingStudent.retired.is_(False))
        .distinct()
    )


def faculty_roles_for_submitting_student(student):
    """Inverse of the role queries above: given a SubmittingStudent, the (User, SubmissionRole,
    SubmissionRecord) triples for every faculty member holding a supervisor / responsible-supervisor
    / marker / moderator role on any of the student's submission records. The SubmissionRole object
    itself is returned (not just its role code) so callers can dispatch on `role.role` and render a
    human-readable label via `role.role_as_str`. Used to populate the ticket assign/subscribe
    pickers' "Related faculty" section (app/tickets/detail.py) — not the compose-flow candidate
    search, so presentation assessor and exam board / external examiner roles are excluded here even
    though they're broader than the roles offered when composing a ticket subject."""
    roles = (
        SubmissionRole.query.join(SubmissionRecord, SubmissionRole.submission_id == SubmissionRecord.id)
        .filter(SubmissionRecord.owner_id == student.id, SubmissionRole.role.in_(_ASSIGNABLE_STUDENT_ROLES))
        .all()
    )
    return [(role.user, role, role.submission) for role in roles if role.user is not None]


def faculty_for_selecting_student(student):
    """Inverse of `faculty_selectee_query`: given a SelectingStudent, the (User, LiveProject) pairs
    for every faculty member who owns a project the student has a live (requested or confirmed)
    sign-off request against. Declined requests are excluded."""
    requests = (
        ConfirmRequest.query.join(LiveProject, ConfirmRequest.project_id == LiveProject.id)
        .filter(
            ConfirmRequest.owner_id == student.id,
            ConfirmRequest.state.in_((ConfirmRequest.REQUESTED, ConfirmRequest.CONFIRMED)),
        )
        .all()
    )
    pairs = []
    for request in requests:
        project = request.project
        if project is None or project.owner is None or project.owner.user is None:
            continue
        pairs.append((project.owner.user, project))
    return pairs


def convenor_submitting_query(pclass):
    config = pclass.most_recent_config
    if config is None:
        return SubmittingStudent.query.filter(SubmittingStudent.id.is_(None))
    return SubmittingStudent.query.filter(SubmittingStudent.config_id == config.id)


def convenor_selecting_query(pclass):
    config = pclass.most_recent_config
    if config is None:
        return SelectingStudent.query.filter(SelectingStudent.id.is_(None))
    return SelectingStudent.query.filter(SelectingStudent.config_id == config.id)


def authorized(user, kind, target, convenor_pclass=None) -> bool:
    """Server-side authorisation: may this user attach this subject to a ticket?

    `convenor_pclass` is a pre-resolved, pre-entitlement-checked ProjectClass (from
    `resolve_convenor_pclass`) when the request is operating in convenor-ledger context; when set,
    it grants scope over that one class independently of the office/faculty branches below.
    """
    if convenor_pclass is not None:
        if kind == TicketSubject.PROJECT_CLASS:
            return target.id == convenor_pclass.id
        hc = home_class(target)
        return hc is not None and hc.id == convenor_pclass.id

    if is_office_like(user):
        tenant_id = target_tenant_id(kind, target)
        return tenant_id is not None and tenant_id in set(user_tenant_ids(user))

    faculty = getattr(user, "faculty_data", None)
    if faculty is None:
        return False

    if kind == TicketSubject.PROJECT_CLASS:
        return target.id in faculty_classes(faculty)
    if kind == TicketSubject.SUBMITTING_STUDENT:
        return faculty_related_student_query(user).filter(SubmittingStudent.id == target.id).first() is not None
    if kind == TicketSubject.SELECTING_STUDENT:
        return faculty_selectee_query(user).filter(SelectingStudent.id == target.id).first() is not None
    return False


# ------------------------------------------------------------------------------------------------
# candidate search (select2 remote) helpers


def name_filter(query_term):
    like = f"%{query_term}%"
    return (User.first_name.ilike(like)) | (User.last_name.ilike(like))


def _student_user(student):
    data = getattr(student, "student", None)
    return getattr(data, "user", None)


def student_name(student) -> str:
    user = _student_user(student)
    return user.name if user is not None else "Student"


def _student_results(model, query_term, tenant_ids, label, include_past=False):
    q = (
        model.query.join(ProjectClassConfig, model.config_id == ProjectClassConfig.id)
        .join(ProjectClass, ProjectClassConfig.pclass_id == ProjectClass.id)
        .join(StudentData, model.student_id == StudentData.id)
        .join(User, StudentData.id == User.id)
        .filter(
            ProjectClass.tenant_id.in_(tenant_ids),
            ProjectClass.active.is_(True),
            ProjectClass.publish.is_(True),
            model.retired.is_(False),
        )
    )
    if not include_past:
        q = q.filter(ProjectClassConfig.year >= get_current_year())
    if query_term:
        q = q.filter(name_filter(query_term))
    kind = TicketSubject.SUBMITTING_STUDENT if model is SubmittingStudent else TicketSubject.SELECTING_STUDENT
    role_label = "Submitter" if model is SubmittingStudent else "Selector"
    rows = []
    for student in q.limit(SEARCH_LIMIT).all():
        hc = home_class(student)
        user = _student_user(student)
        subtitle = f"{role_label} · {hc.name}" if hc is not None else role_label
        rows.append(
            {
                "id": token_for(kind, student.id),
                "text": student_name(student),
                "initials": user.initials if user is not None else "?",
                "colour": user.avatar_colour if user is not None else None,
                "subtitle": subtitle,
            }
        )
    return {"text": label, "children": rows} if rows else None


def _class_results(query_term, tenant_ids):
    q = ProjectClass.query.filter(
        ProjectClass.tenant_id.in_(tenant_ids),
        ProjectClass.active.is_(True),
        ProjectClass.publish.is_(True),
    )
    if query_term:
        q = q.filter(ProjectClass.name.ilike(f"%{query_term}%"))
    rows = [
        {"id": token_for(TicketSubject.PROJECT_CLASS, pclass.id), "text": f"{pclass.name}", "kind": "class"}
        for pclass in q.order_by(ProjectClass.name.asc()).limit(SEARCH_LIMIT).all()
    ]
    return {"text": "Project classes", "children": rows} if rows else None


def convenor_candidates(pclass, query_term):
    """The candidate set for a convenor-ledger context: every submitter/selector anchored on the
    class's current config, plus the class itself as a whole-class token."""
    groups = []

    sub_rows = []
    sub_q = convenor_submitting_query(pclass).join(StudentData, SubmittingStudent.student_id == StudentData.id).join(User, StudentData.id == User.id)
    if query_term:
        sub_q = sub_q.filter(name_filter(query_term))
    for student in sub_q.limit(SEARCH_LIMIT).all():
        user = _student_user(student)
        sub_rows.append(
            {
                "id": token_for(TicketSubject.SUBMITTING_STUDENT, student.id),
                "text": student_name(student),
                "initials": user.initials if user is not None else "?",
                "colour": user.avatar_colour if user is not None else None,
                "subtitle": "Submitter",
            }
        )
    if sub_rows:
        groups.append({"text": "Submitting students", "children": sub_rows})

    sel_rows = []
    sel_q = convenor_selecting_query(pclass).join(StudentData, SelectingStudent.student_id == StudentData.id).join(User, StudentData.id == User.id)
    if query_term:
        sel_q = sel_q.filter(name_filter(query_term))
    for student in sel_q.limit(SEARCH_LIMIT).all():
        user = _student_user(student)
        sel_rows.append(
            {
                "id": token_for(TicketSubject.SELECTING_STUDENT, student.id),
                "text": student_name(student),
                "initials": user.initials if user is not None else "?",
                "colour": user.avatar_colour if user is not None else None,
                "subtitle": "Selector",
            }
        )
    if sel_rows:
        groups.append({"text": "Selecting students", "children": sel_rows})

    if not query_term or query_term.lower() in (pclass.name or "").lower():
        groups.append(
            {
                "text": "Project classes",
                "children": [{"id": token_for(TicketSubject.PROJECT_CLASS, pclass.id), "text": f"{pclass.name}", "kind": "class"}],
            }
        )

    return groups


def _named_role_rows(query, model, kind, query_term, tenant_id, include_past, subtitle_label):
    """Build named (avatar + name) candidate rows for a SubmittingStudent/SelectingStudent query
    already filtered to a specific faculty role. Matches by name."""
    q = query.join(StudentData, model.student_id == StudentData.id).join(User, StudentData.id == User.id)
    if not include_past:
        q = q.join(ProjectClassConfig, model.config_id == ProjectClassConfig.id).filter(ProjectClassConfig.year >= get_current_year())
    if query_term:
        q = q.filter(name_filter(query_term))
    rows = []
    for student in q.limit(SEARCH_LIMIT).all():
        hc = home_class(student)
        if tenant_id is not None and (hc is None or hc.tenant_id != tenant_id):
            continue
        user_ = _student_user(student)
        subtitle = f"{subtitle_label} · {hc.name}" if hc is not None else subtitle_label
        rows.append(
            {
                "id": token_for(kind, student.id),
                "text": student_name(student),
                "initials": user_.initials if user_ is not None else "?",
                "colour": user_.avatar_colour if user_ is not None else None,
                "subtitle": subtitle,
            }
        )
    return rows


def _anonymised_role_rows(query, query_term, tenant_id, include_past, subtitle_label):
    """Build exam-number-only candidate rows (no name, no avatar) for a SubmittingStudent query
    already filtered to a specific faculty role (marker/moderator), to preserve blind-marking
    anonymity. `exam_number` is an encrypted column, so it can't be filtered in SQL — matches
    against `query_term` are done in Python, against the exam number only, never the student's
    name."""
    q = query
    if not include_past:
        q = q.join(ProjectClassConfig, SubmittingStudent.config_id == ProjectClassConfig.id).filter(ProjectClassConfig.year >= get_current_year())
    rows = []
    for student in q.order_by(SubmittingStudent.id).limit(500).all():
        hc = home_class(student)
        if tenant_id is not None and (hc is None or hc.tenant_id != tenant_id):
            continue
        data = getattr(student, "student", None)
        exam_number = getattr(data, "exam_number", None)
        if exam_number is None:
            continue
        exam_str = str(exam_number)
        if query_term and query_term not in exam_str:
            continue
        subtitle = f"{subtitle_label} · {hc.name}" if hc is not None else subtitle_label
        rows.append(
            {
                "id": token_for(TicketSubject.SUBMITTING_STUDENT, student.id),
                "text": f"#{exam_number}",
                "kind": "anon",
                "subtitle": subtitle,
            }
        )
        if len(rows) >= SEARCH_LIMIT:
            break
    return rows


def faculty_candidates(user, query_term, tenant_id=None, include_past=False):
    groups = []
    faculty = user.faculty_data

    classes = list(faculty_classes(faculty).values())
    if tenant_id is not None:
        classes = [pclass for pclass in classes if pclass.tenant_id == tenant_id]
    if query_term:
        classes = [pclass for pclass in classes if query_term.lower() in (pclass.name or "").lower()]
    class_rows = [{"id": token_for(TicketSubject.PROJECT_CLASS, pclass.id), "text": f"{pclass.name}", "kind": "class"} for pclass in classes]
    if class_rows:
        groups.append({"text": "Your classes", "children": class_rows[:SEARCH_LIMIT]})

    sup_rows = _named_role_rows(
        faculty_supervisee_query(user), SubmittingStudent, TicketSubject.SUBMITTING_STUDENT, query_term, tenant_id, include_past, "Supervised by you"
    )
    if sup_rows:
        groups.append({"text": "Your supervisees", "children": sup_rows})

    assessor_rows = _named_role_rows(
        faculty_assessor_query(user), SubmittingStudent, TicketSubject.SUBMITTING_STUDENT, query_term, tenant_id, include_past, "You assess"
    )
    if assessor_rows:
        groups.append({"text": "Students you assess", "children": assessor_rows})

    marker_rows = _anonymised_role_rows(faculty_marker_query(user), query_term, tenant_id, include_past, "You mark")
    if marker_rows:
        groups.append({"text": "Students you mark", "children": marker_rows})

    moderator_rows = _anonymised_role_rows(faculty_moderator_query(user), query_term, tenant_id, include_past, "You moderate")
    if moderator_rows:
        groups.append({"text": "Students you moderate", "children": moderator_rows})

    sel_rows = _named_role_rows(
        faculty_selectee_query(user),
        SelectingStudent,
        TicketSubject.SELECTING_STUDENT,
        query_term,
        tenant_id,
        include_past,
        "Requesting selector sign-off",
    )
    if sel_rows:
        groups.append({"text": "Your selectees", "children": sel_rows})

    return groups


def office_candidates(user, query_term, tenant_id=None, include_past=False):
    tenant_ids = user_tenant_ids(user)
    if tenant_id is not None:
        tenant_ids = [tenant_id] if tenant_id in tenant_ids else []
    if not tenant_ids:
        return []
    groups = []
    for section in (
        _student_results(SubmittingStudent, query_term, tenant_ids, "Submitting students", include_past),
        _student_results(SelectingStudent, query_term, tenant_ids, "Selecting students", include_past),
        _class_results(query_term, tenant_ids),
    ):
        if section is not None:
            groups.append(section)
    return groups


def scope_kind_for(user, *, origin=None, pclass_id=None):
    """Which of the three scope cases a request resolves to.

    Convenor context (explicit `origin` + an entitled `pclass`) takes priority; otherwise a user
    who has `faculty_data` always gets faculty scoping, regardless of any office/admin/root roles
    also held; office scoping is the fallback only for users with no `faculty_data` at all. This is
    the single source of truth for the dispatch below and for any UI (hint text, toggle
    visibility) that needs to know which case is in effect without re-deriving it.
    """
    if origin == "convenor" and resolve_convenor_pclass(user, pclass_id) is not None:
        return "convenor"
    if getattr(user, "faculty_data", None) is not None:
        return "faculty"
    return "office"


def candidates_for(user, query_term, *, origin=None, pclass_id=None, tenant_id=None, include_past=False):
    """Top-level candidate dispatch; see `scope_kind_for` for the precedence rules."""
    kind = scope_kind_for(user, origin=origin, pclass_id=pclass_id)
    if kind == "convenor":
        return convenor_candidates(resolve_convenor_pclass(user, pclass_id), query_term)
    if kind == "faculty":
        return faculty_candidates(user, query_term, tenant_id, include_past)
    return office_candidates(user, query_term, tenant_id, include_past)
