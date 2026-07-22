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
    Label,
    ProjectClass,
    ProjectClassConfig,
    SubmittingStudent,
    Tenant,
    TicketSubject,
)
from ..shared.context.convenor_dashboard import get_convenor_dashboard_data
from ..shared.context.faculty_dashboard import get_faculty_dashboard_data
from ..shared.context.global_context import render_template_context
from ..shared.context.root_dashboard import get_root_dashboard_data
from ..shared.tickets import (
    add_label,
    authorized,
    candidates_for,
    class_convenor_users,
    create_ticket,
    faculty_classes,
    faculty_supervisee_query,
    home_class,
    is_office_like,
    primary_convenor_user,
    resolve_convenor_pclass,
    resolve_token,
    scope_kind_for,
    student_name,
    target_tenant_id,
    user_tenant_ids,
)
from ..shared.workflow_logging import log_db_commit
from ..shared.utils import redirect_url
from .forms import TicketComposeForm


def _available_tenants(user):
    """Distinct tenants the acting user could compose a ticket against, for the tenant selector.

    Mirrors `scope_kind_for`'s priority: a user with `faculty_data` gets the tenants of the classes
    they supervise plus the home-class tenants of their supervisees, regardless of any
    office/admin/root roles also held; office/admin/root's subscribed tenants are the fallback only
    for users with no `faculty_data` at all. Returned sorted by name. A ticket is single-tenant, so
    this only drives a chooser that keeps the subject picker within one tenant.
    """
    faculty = getattr(user, "faculty_data", None)
    if faculty is not None:
        tenant_ids = {pclass.tenant_id for pclass in faculty_classes(faculty).values() if pclass.tenant_id is not None}
        sup_tenant_ids = (
            faculty_supervisee_query(user)
            .join(ProjectClassConfig, SubmittingStudent.config_id == ProjectClassConfig.id)
            .join(ProjectClass, ProjectClassConfig.pclass_id == ProjectClass.id)
            .with_entities(ProjectClass.tenant_id)
            .distinct()
        )
        tenant_ids.update(tid for (tid,) in sup_tenant_ids if tid is not None)
        if not tenant_ids:
            return []
        return Tenant.query.filter(Tenant.id.in_(tenant_ids)).order_by(Tenant.name.asc()).all()

    if is_office_like(user):
        return user.tenants.order_by(Tenant.name.asc()).all()

    return []


# ------------------------------------------------------------------------------------------------
# routing preview


def _routing_preview(user, tokens, convenor_pclass=None):
    classes = {}
    for token in tokens:
        resolved = resolve_token(token)
        if resolved is None:
            continue
        kind, target = resolved
        if not authorized(user, kind, target, convenor_pclass=convenor_pclass):
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
    tenant_ids = user_tenant_ids(user)
    if not tenant_ids:
        return []
    return Label.query.filter(Label.tenant_id.in_(tenant_ids)).order_by(Label.name.asc()).all()


def _selected_subject_options(tokens):
    """Rebuild <option> label text for already-selected tokens (needed to re-render a select2)."""
    options = []
    for token in tokens:
        resolved = resolve_token(token)
        if resolved is None:
            continue
        kind, target = resolved
        if kind == TicketSubject.PROJECT_CLASS:
            options.append((token, f"{target.name} (whole class)"))
        else:
            options.append((token, student_name(target)))
    return options


def _origin_pclass_compose():
    """Resolve the `pclass` query arg to a ProjectClass the current user convenes/co-convenes, but
    only when `origin=convenor` (matching `_compose_template`'s chrome gate)."""
    if request.args.get("origin") != "convenor":
        return None
    return resolve_convenor_pclass(current_user, request.args.get("pclass", type=int))


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
    convenor_pclass = _origin_pclass_compose()
    scope_kind = scope_kind_for(current_user, origin=origin, pclass_id=pclass_id)
    template, nav_ctx = _compose_template()
    cancel_url = _cancel_url(origin, nav_ctx.get("pclass"))

    def _render():
        return render_template_context(
            template,
            **nav_ctx,
            form=form,
            labels=labels,
            label_styles={label.id: (label.make_CSS_style() or "") for label in labels},
            scope_kind=scope_kind,
            tenants=_available_tenants(current_user),
            origin=origin,
            pclass_id=pclass_id,
            cancel_url=cancel_url,
        )

    if form.validate_on_submit():
        tokens = form.subjects.data or []

        resolved = []
        for token in tokens:
            item = resolve_token(token)
            if item is None or not authorized(current_user, *item, convenor_pclass=convenor_pclass):
                flash("One of the selected subjects is invalid or outside your permitted scope.", "error")
                form.subjects.choices = _selected_subject_options(tokens)
                return _render()
            resolved.append(item)

        # A ticket concerns exactly one tenant: reject a subject set that spans more than one
        # (the tenant selector prevents this in the UI; this is the server-side backstop).
        tenant_ids = {tid for tid in (target_tenant_id(kind, target) for kind, target in resolved) if tid is not None}
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
    groups = candidates_for(
        current_user,
        query_term,
        origin=request.args.get("origin"),
        pclass_id=request.args.get("pclass", type=int),
        tenant_id=tenant_id,
        include_past=include_past,
    )
    return jsonify({"results": groups})


@tickets.route("/compose/routing")
@roles_accepted("faculty", "office", "admin", "root")
def compose_routing():
    """JSON live-preview of routing/auto-assign consequences for the selected subjects."""
    tokens = request.args.getlist("t")
    convenor_pclass = _origin_pclass_compose()
    return jsonify(_routing_preview(current_user, tokens, convenor_pclass=convenor_pclass))
