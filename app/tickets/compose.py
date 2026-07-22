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
from ..shared.context.convenor_dashboard import get_convenor_dashboard_data
from ..shared.context.faculty_dashboard import get_faculty_dashboard_data
from ..shared.context.global_context import render_template_context
from ..shared.context.root_dashboard import get_root_dashboard_data
from ..shared.tickets import (
    add_label,
    class_convenor_users,
    create_ticket,
    home_class,
    primary_convenor_user,
)
from ..shared.workflow_logging import log_db_commit
from ..shared.utils import get_current_year, redirect_url
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


def _student_user(student):
    data = getattr(student, "student", None)
    return getattr(data, "user", None)


def _student_name(student):
    user = _student_user(student)
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


def _student_results(model, query_term, tenant_ids, label, include_past=False):
    q = (
        model.query.join(ProjectClassConfig, model.config_id == ProjectClassConfig.id)
        .join(ProjectClass, ProjectClassConfig.pclass_id == ProjectClass.id)
        .join(StudentData, model.student_id == StudentData.id)
        .join(User, StudentData.id == User.id)
        .filter(ProjectClass.tenant_id.in_(tenant_ids))
    )
    if not include_past:
        q = q.filter(ProjectClassConfig.year >= get_current_year())
    if query_term:
        q = q.filter(_name_filter(query_term))
    kind = TicketSubject.SUBMITTING_STUDENT if model is SubmittingStudent else TicketSubject.SELECTING_STUDENT
    role_label = "Submitter" if model is SubmittingStudent else "Selector"
    rows = []
    for student in q.limit(_SEARCH_LIMIT).all():
        hc = home_class(student)
        user = _student_user(student)
        subtitle = f"{role_label} · {hc.name}" if hc is not None else role_label
        rows.append(
            {
                "id": _token(kind, student.id),
                "text": _student_name(student),
                "initials": user.initials if user is not None else "?",
                "subtitle": subtitle,
            }
        )
    return {"text": label, "children": rows} if rows else None


def _class_results(query_term, tenant_ids):
    q = ProjectClass.query.filter(ProjectClass.tenant_id.in_(tenant_ids))
    if query_term:
        q = q.filter(ProjectClass.name.ilike(f"%{query_term}%"))
    rows = [
        {"id": _token(TicketSubject.PROJECT_CLASS, pclass.id), "text": f"{pclass.name} (whole class)", "kind": "class"}
        for pclass in q.order_by(ProjectClass.name.asc()).limit(_SEARCH_LIMIT).all()
    ]
    return {"text": "Project classes", "children": rows} if rows else None


def _faculty_candidates(user, query_term, tenant_id=None, include_past=False):
    groups = []
    faculty = user.faculty_data

    classes = list(_faculty_classes(faculty).values())
    if tenant_id is not None:
        classes = [pclass for pclass in classes if pclass.tenant_id == tenant_id]
    if query_term:
        classes = [pclass for pclass in classes if query_term.lower() in (pclass.name or "").lower()]
    class_rows = [
        {"id": _token(TicketSubject.PROJECT_CLASS, pclass.id), "text": f"{pclass.name} (whole class)", "kind": "class"} for pclass in classes
    ]
    if class_rows:
        groups.append({"text": "Your classes", "children": class_rows[:_SEARCH_LIMIT]})

    sup_query = (
        _faculty_supervisee_query(user).join(StudentData, SubmittingStudent.student_id == StudentData.id).join(User, StudentData.id == User.id)
    )
    if not include_past:
        sup_query = sup_query.join(ProjectClassConfig, SubmittingStudent.config_id == ProjectClassConfig.id).filter(
            ProjectClassConfig.year >= get_current_year()
        )
    if query_term:
        sup_query = sup_query.filter(_name_filter(query_term))
    sup_rows = []
    for student in sup_query.limit(_SEARCH_LIMIT).all():
        hc = home_class(student)
        if tenant_id is not None and (hc is None or hc.tenant_id != tenant_id):
            continue
        user = _student_user(student)
        subtitle = f"Supervised by you · {hc.name}" if hc is not None else "Supervised by you"
        sup_rows.append(
            {
                "id": _token(TicketSubject.SUBMITTING_STUDENT, student.id),
                "text": _student_name(student),
                "initials": user.initials if user is not None else "?",
                "subtitle": subtitle,
            }
        )
    if sup_rows:
        groups.append({"text": "Your supervisees", "children": sup_rows})

    return groups


def _office_candidates(user, query_term, tenant_id=None, include_past=False):
    tenant_ids = _user_tenant_ids(user)
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

    seen_convenors = {}
    for pclass in class_list:
        for u in class_convenor_users(pclass):
            seen_convenors[u.id] = u
    convenors = [{"name": u.name, "initials": u.initials} for u in sorted(seen_convenors.values(), key=lambda u: u.name)]

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


def _origin_pclass_compose():
    """Resolve the `pclass` query arg to a ProjectClass, but only if the current user
    convenes/co-convenes it. Same entitlement check as `detail._origin_pclass`, minus the
    ticket-scope test (compose has no ticket to scope against yet)."""
    pclass_id = request.args.get("pclass", type=int)
    if pclass_id is None:
        return None

    faculty = getattr(current_user, "faculty_data", None)
    if faculty is None:
        return None
    convened = {p.id for p in faculty.convenor_for} | {p.id for p in faculty.coconvenor_for}
    if pclass_id not in convened:
        return None

    return ProjectClass.query.get(pclass_id)


def _compose_template():
    """Pick the per-surface wrapper template + its nav context from the `origin` the inbound link
    carried. Mirrors `detail._detail_template`, minus the ticket-scope test."""
    origin = request.args.get("origin")

    if origin == "convenor":
        pclass = _origin_pclass_compose()
        if pclass is not None:
            config = pclass.most_recent_config
            if config is not None:
                return "tickets/convenor_compose.html", {
                    "pane": "tickets",
                    "pclass": pclass,
                    "config": config,
                    "convenor_data": get_convenor_dashboard_data(pclass, config),
                }

    elif origin == "faculty" and current_user.has_role("faculty"):
        nav_ctx = {"pane": "tickets", **get_faculty_dashboard_data(current_user)}
        if current_user.has_role("root"):
            nav_ctx["root_dash_data"] = get_root_dashboard_data()
        return "faculty/dashboard/faculty_compose.html", nav_ctx

    return "tickets/compose.html", {}


def _cancel_url(origin, pclass):
    """Where the Cancel button / breadcrumb 'Tickets' link should send the user, matching the
    chrome the page rendered with (same fallback logic as `detail._breadcrumb`)."""
    if origin == "convenor" and pclass is not None:
        return url_for("convenor.tickets_tab", id=pclass.id)
    if origin == "faculty":
        return url_for("faculty.dashboard_tickets")
    return url_for("tickets.inbox")


@tickets.route("/compose", methods=["GET", "POST"])
@roles_accepted("faculty", "office", "admin", "root")
def compose():
    form = TicketComposeForm()

    labels = _label_choices(current_user)
    form.labels.choices = [(label.id, label.name) for label in labels]

    origin = request.args.get("origin")
    pclass_id = request.args.get("pclass", type=int)
    template, nav_ctx = _compose_template()
    cancel_url = _cancel_url(origin, nav_ctx.get("pclass"))

    def _render():
        return render_template_context(
            template,
            **nav_ctx,
            form=form,
            office_scope=_is_office_like(current_user),
            tenants=_available_tenants(current_user),
            origin=origin,
            pclass_id=pclass_id,
            cancel_url=cancel_url,
        )

    if form.validate_on_submit():
        tokens = form.subjects.data or []

        resolved = []
        for token in tokens:
            item = _resolve_token(token)
            if item is None or not _authorized(current_user, *item):
                flash("One of the selected subjects is invalid or outside your permitted scope.", "error")
                form.subjects.choices = _selected_subject_options(tokens)
                return _render()
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
            return _render()

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

        return redirect(url_for("tickets.detail", ticket_id=ticket.id, origin=origin, pclass=pclass_id))

    # GET (or invalid submit that fell through) — echo any posted tokens back into the select
    form.subjects.choices = _selected_subject_options(form.subjects.data or [])
    return _render()


@tickets.route("/compose/people")
@roles_accepted("faculty", "office", "admin", "root")
def compose_people():
    """select2 remote data: role-scoped candidate students / classes for the subject picker."""
    query_term = (request.args.get("q") or "").strip()
    tenant_id = request.args.get("tenant_id", type=int)
    include_past = bool(request.args.get("include_past", type=int))
    if _is_office_like(current_user):
        groups = _office_candidates(current_user, query_term, tenant_id, include_past)
    else:
        groups = _faculty_candidates(current_user, query_term, tenant_id, include_past)
    return jsonify({"results": groups})


@tickets.route("/compose/routing")
@roles_accepted("faculty", "office", "admin", "root")
def compose_routing():
    """JSON live-preview of routing/auto-assign consequences for the selected subjects."""
    tokens = request.args.getlist("t")
    return jsonify(_routing_preview(current_user, tokens))
