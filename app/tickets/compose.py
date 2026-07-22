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
Compose flow for new tickets (design screens 2b faculty / 3b office).

One route serves both variants; the candidate subject set is scoped by the acting user's role:
faculty may attach their supervisees (submitting students they supervise) and their supervised
classes; office / admin / root may attach any submitting or selecting student, or whole class, in
their subscribed tenants. Scope is enforced server-side on every submitted token, never trusted
from the client. A JSON endpoint powers the live routing/auto-assign preview.
"""

from flask import current_app, flash, jsonify, redirect, request, url_for
from flask_security import current_user, roles_accepted
from sqlalchemy.exc import SQLAlchemyError

from app.tickets import tickets

from ..database import db
from ..models import (
    EnrollmentRecord,
    Label,
    ProjectClass,
    ProjectClassConfig,
    SelectingStudent,
    StudentData,
    SubmissionRecord,
    SubmissionRole,
    SubmittingStudent,
    Tenant,
    TicketSubject,
    User,
)
from ..shared.context.global_context import render_template_context
from ..shared.tickets import (
    add_label,
    class_convenor_users,
    create_ticket,
    home_class,
    primary_convenor_user,
)
from ..shared.workflow_logging import log_db_commit
from ..shared.utils import redirect_url
from .forms import TicketComposeForm

_SUP_ROLES = (SubmissionRole.ROLE_SUPERVISOR, SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR)

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

_SEARCH_LIMIT = 20


# ------------------------------------------------------------------------------------------------
# role / scope helpers


def _is_office_like(user) -> bool:
    return user.has_role("office") or user.has_role("admin") or user.has_role("root")


def _user_tenant_ids(user):
    return [tenant.id for tenant in user.tenants]


def _token(kind, obj_id) -> str:
    return f"{_PREFIX_BY_KIND[kind]}:{obj_id}"


def _resolve_token(token):
    prefix, _, sid = token.partition(":")
    kind = _KIND_BY_PREFIX.get(prefix)
    if kind is None or not sid.isdigit():
        return None
    obj = _MODEL_BY_KIND[kind].query.get(int(sid))
    if obj is None:
        return None
    return kind, obj


def _student_name(student):
    data = getattr(student, "student", None)
    user = getattr(data, "user", None)
    return user.name if user is not None else "Student"


def _target_tenant_id(kind, target):
    if kind == TicketSubject.PROJECT_CLASS:
        return target.tenant_id
    hc = home_class(target)
    return hc.tenant_id if hc is not None else None


def _faculty_classes(faculty):
    """Classes a faculty member supervises: convened + co-convened + enrolled-as-supervisor."""
    classes = {}
    for pclass in faculty.convenor_for:
        classes[pclass.id] = pclass
    for pclass in faculty.coconvenor_for:
        classes[pclass.id] = pclass
    for enrollment in faculty.enrollments:
        if enrollment.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED and enrollment.pclass is not None:
            classes[enrollment.pclass.id] = enrollment.pclass
    return classes


def _faculty_supervisee_query(user):
    return (
        SubmittingStudent.query.join(SubmissionRecord, SubmissionRecord.owner_id == SubmittingStudent.id)
        .join(SubmissionRole, SubmissionRole.submission_id == SubmissionRecord.id)
        .filter(SubmissionRole.user_id == user.id, SubmissionRole.role.in_(_SUP_ROLES))
        .distinct()
    )


def _available_tenants(user):
    """Distinct tenants the acting user could compose a ticket against, for the tenant selector.

    Office/admin/root → the user's subscribed tenants. Faculty → the tenants of the classes they
    supervise plus the home-class tenants of their supervisees. Returned sorted by name. A ticket
    is single-tenant, so this only drives a chooser that keeps the subject picker within one tenant.
    """
    if _is_office_like(user):
        return user.tenants.order_by(Tenant.name.asc()).all()

    faculty = getattr(user, "faculty_data", None)
    if faculty is None:
        return []

    tenant_ids = {pclass.tenant_id for pclass in _faculty_classes(faculty).values() if pclass.tenant_id is not None}
    sup_tenant_ids = (
        _faculty_supervisee_query(user)
        .join(ProjectClassConfig, SubmittingStudent.config_id == ProjectClassConfig.id)
        .join(ProjectClass, ProjectClassConfig.pclass_id == ProjectClass.id)
        .with_entities(ProjectClass.tenant_id)
        .distinct()
    )
    tenant_ids.update(tid for (tid,) in sup_tenant_ids if tid is not None)
    if not tenant_ids:
        return []
    return Tenant.query.filter(Tenant.id.in_(tenant_ids)).order_by(Tenant.name.asc()).all()


def _authorized(user, kind, target) -> bool:
    """Server-side authorisation: may this user attach this subject to a ticket?"""
    if _is_office_like(user):
        tenant_id = _target_tenant_id(kind, target)
        return tenant_id is not None and tenant_id in set(_user_tenant_ids(user))

    faculty = getattr(user, "faculty_data", None)
    if faculty is None:
        return False

    if kind == TicketSubject.PROJECT_CLASS:
        return target.id in _faculty_classes(faculty)
    if kind == TicketSubject.SUBMITTING_STUDENT:
        return _faculty_supervisee_query(user).filter(SubmittingStudent.id == target.id).first() is not None
    # faculty cannot attach selecting students (their scope is supervisees + supervised classes)
    return False


# ------------------------------------------------------------------------------------------------
# candidate search (select2 remote) helpers


def _name_filter(query_term):
    like = f"%{query_term}%"
    return (User.first_name.ilike(like)) | (User.last_name.ilike(like))


def _student_results(model, query_term, tenant_ids, label):
    q = (
        model.query.join(ProjectClassConfig, model.config_id == ProjectClassConfig.id)
        .join(ProjectClass, ProjectClassConfig.pclass_id == ProjectClass.id)
        .join(StudentData, model.student_id == StudentData.id)
        .join(User, StudentData.id == User.id)
        .filter(ProjectClass.tenant_id.in_(tenant_ids))
    )
    if query_term:
        q = q.filter(_name_filter(query_term))
    kind = TicketSubject.SUBMITTING_STUDENT if model is SubmittingStudent else TicketSubject.SELECTING_STUDENT
    rows = []
    for student in q.limit(_SEARCH_LIMIT).all():
        hc = home_class(student)
        suffix = f" · {hc.name}" if hc is not None else ""
        rows.append({"id": _token(kind, student.id), "text": f"{_student_name(student)}{suffix}"})
    return {"text": label, "children": rows} if rows else None


def _class_results(query_term, tenant_ids):
    q = ProjectClass.query.filter(ProjectClass.tenant_id.in_(tenant_ids))
    if query_term:
        q = q.filter(ProjectClass.name.ilike(f"%{query_term}%"))
    rows = [
        {"id": _token(TicketSubject.PROJECT_CLASS, pclass.id), "text": f"{pclass.name} (whole class)"}
        for pclass in q.order_by(ProjectClass.name.asc()).limit(_SEARCH_LIMIT).all()
    ]
    return {"text": "Project classes", "children": rows} if rows else None


def _faculty_candidates(user, query_term, tenant_id=None):
    groups = []
    faculty = user.faculty_data

    classes = list(_faculty_classes(faculty).values())
    if tenant_id is not None:
        classes = [pclass for pclass in classes if pclass.tenant_id == tenant_id]
    if query_term:
        classes = [pclass for pclass in classes if query_term.lower() in (pclass.name or "").lower()]
    class_rows = [{"id": _token(TicketSubject.PROJECT_CLASS, pclass.id), "text": f"{pclass.name} (whole class)"} for pclass in classes]
    if class_rows:
        groups.append({"text": "Your classes", "children": class_rows[:_SEARCH_LIMIT]})

    sup_query = (
        _faculty_supervisee_query(user).join(StudentData, SubmittingStudent.student_id == StudentData.id).join(User, StudentData.id == User.id)
    )
    if query_term:
        sup_query = sup_query.filter(_name_filter(query_term))
    sup_rows = []
    for student in sup_query.limit(_SEARCH_LIMIT).all():
        hc = home_class(student)
        if tenant_id is not None and (hc is None or hc.tenant_id != tenant_id):
            continue
        suffix = f" · {hc.name}" if hc is not None else ""
        sup_rows.append({"id": _token(TicketSubject.SUBMITTING_STUDENT, student.id), "text": f"{_student_name(student)}{suffix}"})
    if sup_rows:
        groups.append({"text": "Your supervisees", "children": sup_rows})

    return groups


def _office_candidates(user, query_term, tenant_id=None):
    tenant_ids = _user_tenant_ids(user)
    if tenant_id is not None:
        tenant_ids = [tenant_id] if tenant_id in tenant_ids else []
    if not tenant_ids:
        return []
    groups = []
    for section in (
        _student_results(SubmittingStudent, query_term, tenant_ids, "Submitting students"),
        _student_results(SelectingStudent, query_term, tenant_ids, "Selecting students"),
        _class_results(query_term, tenant_ids),
    ):
        if section is not None:
            groups.append(section)
    return groups


# ------------------------------------------------------------------------------------------------
# routing preview


def _routing_preview(user, tokens):
    classes = {}
    for token in tokens:
        resolved = _resolve_token(token)
        if resolved is None:
            continue
        kind, target = resolved
        if not _authorized(user, kind, target):
            continue
        if kind == TicketSubject.PROJECT_CLASS:
            classes[target.id] = target
        else:
            hc = home_class(target)
            if hc is not None:
                classes[hc.id] = hc

    class_list = list(classes.values())
    count = len(class_list)

    assignee = None
    auto = False
    if count == 1:
        convenor = primary_convenor_user(class_list[0])
        if convenor is not None:
            assignee = convenor.name
            auto = True

    convenors = sorted({u.name for pclass in class_list for u in class_convenor_users(pclass)})

    return {
        "count": count,
        "multi": count > 1,
        "auto": auto,
        "assignee": assignee,
        "convenors": convenors,
        "classes": [pclass.name for pclass in class_list],
    }


# ------------------------------------------------------------------------------------------------
# views


def _label_choices(user):
    tenant_ids = _user_tenant_ids(user)
    if not tenant_ids:
        return []
    return Label.query.filter(Label.tenant_id.in_(tenant_ids)).order_by(Label.name.asc()).all()


def _selected_subject_options(tokens):
    """Rebuild <option> label text for already-selected tokens (needed to re-render a select2)."""
    options = []
    for token in tokens:
        resolved = _resolve_token(token)
        if resolved is None:
            continue
        kind, target = resolved
        if kind == TicketSubject.PROJECT_CLASS:
            options.append((token, f"{target.name} (whole class)"))
        else:
            options.append((token, _student_name(target)))
    return options


@tickets.route("/compose", methods=["GET", "POST"])
@roles_accepted("faculty", "office", "admin", "root")
def compose():
    form = TicketComposeForm()

    labels = _label_choices(current_user)
    form.labels.choices = [(label.id, label.name) for label in labels]

    if form.validate_on_submit():
        tokens = form.subjects.data or []

        resolved = []
        for token in tokens:
            item = _resolve_token(token)
            if item is None or not _authorized(current_user, *item):
                flash("One of the selected subjects is invalid or outside your permitted scope.", "error")
                form.subjects.choices = _selected_subject_options(tokens)
                return render_template_context(
                    "tickets/compose.html", form=form, office_scope=_is_office_like(current_user), tenants=_available_tenants(current_user)
                )
            resolved.append(item)

        # A ticket concerns exactly one tenant: reject a subject set that spans more than one
        # (the tenant selector prevents this in the UI; this is the server-side backstop).
        tenant_ids = {tid for tid in (_target_tenant_id(kind, target) for kind, target in resolved) if tid is not None}
        if len(tenant_ids) > 1:
            flash(
                "A ticket can only concern one tenant. The selected subjects belong to more than one; please split them into separate tickets.",
                "error",
            )
            form.subjects.choices = _selected_subject_options(tokens)
            return render_template_context(
                "tickets/compose.html", form=form, office_scope=_is_office_like(current_user), tenants=_available_tenants(current_user)
            )

        ticket = create_ticket(
            title=form.title.data,
            opener=current_user,
            description=form.description.data,
            subjects=resolved,
            due_date=form.due_date.data,
        )

        # apply selected labels that belong to the resulting ticket's tenant
        for label_id in form.labels.data or []:
            label = Label.query.get(label_id)
            if label is not None and label.tenant_id == ticket.tenant_id:
                add_label(ticket, label, actor=current_user)

        try:
            log_db_commit(
                f"Opened ticket #{ticket.id}",
                user=current_user,
                project_classes=list(ticket.scope_classes),
            )
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=exc)
            flash("Could not open the ticket due to a database error. Please contact a system administrator.", "error")
            return redirect(redirect_url())

        return redirect(url_for("tickets.detail", ticket_id=ticket.id))

    # GET (or invalid submit that fell through) — echo any posted tokens back into the select
    form.subjects.choices = _selected_subject_options(form.subjects.data or [])
    return render_template_context(
        "tickets/compose.html", form=form, office_scope=_is_office_like(current_user), tenants=_available_tenants(current_user)
    )


@tickets.route("/compose/people")
@roles_accepted("faculty", "office", "admin", "root")
def compose_people():
    """select2 remote data: role-scoped candidate students / classes for the subject picker."""
    query_term = (request.args.get("q") or "").strip()
    tenant_id = request.args.get("tenant_id", type=int)
    if _is_office_like(current_user):
        groups = _office_candidates(current_user, query_term, tenant_id)
    else:
        groups = _faculty_candidates(current_user, query_term, tenant_id)
    return jsonify({"results": groups})


@tickets.route("/compose/routing")
@roles_accepted("faculty", "office", "admin", "root")
def compose_routing():
    """JSON live-preview of routing/auto-assign consequences for the selected subjects."""
    tokens = request.args.getlist("t")
    return jsonify(_routing_preview(current_user, tokens))
