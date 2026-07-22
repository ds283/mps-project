#
# Created by David Seery on 22/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Ticket dashboards (tickets blueprint): the faculty/office personal inbox (design screen 2c) and the
shared server-side ledger AJAX feed (1a), plus the scope-agnostic claim / bulk actions. The
convenor per-class ticket dashboard (3a) lives in the convenor blueprint (convenor.tickets_tab) so
it renders inside the shared per-class dashboard chrome. The ledger endpoint always receives a
permission-scoped base query built here; scope is never taken from the client.
"""

from datetime import datetime

from flask import abort, current_app, flash, redirect, request, url_for
from flask_security import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

import app.ajax as ajax
from app.tickets import tickets

from ..database import db
from ..models import Label, ProjectClass, Ticket, TicketSubscription
from ..shared.context.global_context import render_template_context
from ..shared.forms.forms import ConfirmActionForm
from ..shared.tickets import (
    add_label,
    assign,
    can_assign,
    can_change_status,
    can_label,
    change_status,
    remove_label,
    unassign,
)
from ..shared.utils import redirect_url
from ..shared.workflow_logging import log_db_commit


# ------------------------------------------------------------------------------------------------
# scope helpers


def _is_admin_or_root(user) -> bool:
    return user.has_role("admin") or user.has_role("root")


def _convened_class_ids(user):
    """Ids of classes the user convenes; None means "all classes" (admin/root)."""
    if _is_admin_or_root(user):
        return None
    faculty = getattr(user, "faculty_data", None)
    if faculty is None:
        return set()
    ids = {pclass.id for pclass in faculty.convenor_for}
    ids.update(pclass.id for pclass in faculty.coconvenor_for)
    return ids


def _mine_base_query(user, view: str):
    assigned = Ticket.assignee_id == user.id
    watched = Ticket.subscriptions.any(TicketSubscription.user_id == user.id)
    if view == "assigned":
        condition = assigned
    elif view == "watching":
        condition = watched
    else:
        condition = or_(assigned, watched)
    return Ticket.query.filter(condition)


def _convenor_base_query(user, class_id):
    ids = _convened_class_ids(user)
    query = Ticket.query
    if class_id is not None:
        if ids is not None and class_id not in ids:
            abort(403)
        return query.filter(Ticket.scope_classes.any(ProjectClass.id == class_id))
    if ids is not None:
        return query.filter(Ticket.scope_classes.any(ProjectClass.id.in_(ids)))
    return query


def _apply_common_filters(query, args):
    status = args.get("status", type=int)
    if status is not None:
        query = query.filter(Ticket.status == status)
    label_id = args.get("label_id", type=int)
    if label_id is not None:
        query = query.filter(Ticket.labels.any(Label.id == label_id))
    return query


def _user_labels(user):
    tenant_ids = [tenant.id for tenant in user.tenants]
    if not tenant_ids:
        return []
    return Label.query.filter(Label.tenant_id.in_(tenant_ids)).order_by(Label.name.asc()).all()


# ------------------------------------------------------------------------------------------------
# AJAX ledger feed


@tickets.route("/ledger_ajax")
@login_required
def ledger_ajax():
    mode = request.args.get("mode", "mine")
    if mode == "convenor":
        base_query = _convenor_base_query(current_user, request.args.get("class_id", type=int))
    else:
        base_query = _mine_base_query(current_user, request.args.get("view", "all"))

    base_query = _apply_common_filters(base_query, request.args).order_by(Ticket.last_edit_timestamp.desc())
    return ajax.tickets.ledger_data(base_query)


# ------------------------------------------------------------------------------------------------
# faculty / office inbox (2c)


@tickets.route("/inbox")
@login_required
def inbox():
    view = request.args.get("view", "all")
    if view not in ("all", "assigned", "watching"):
        view = "all"

    assigned_open = Ticket.query.filter(Ticket.assignee_id == current_user.id, Ticket.status.in_(Ticket.OPEN_STATES)).count()
    watching = Ticket.query.filter(Ticket.subscriptions.any(TicketSubscription.user_id == current_user.id)).count()
    overdue = Ticket.query.filter(
        Ticket.assignee_id == current_user.id,
        Ticket.status.in_(Ticket.OPEN_STATES),
        Ticket.due_date.isnot(None),
        Ticket.due_date < datetime.now(),
    ).count()

    return render_template_context(
        "tickets/inbox.html",
        view=view,
        labels=_user_labels(current_user),
        selected_label=request.args.get("label_id", type=int),
        selected_status=request.args.get("status", type=int),
        metrics={"assigned": assigned_open, "watching": watching, "overdue": overdue},
        all_statuses=[(value, label) for value, label in Ticket._labels.items()],
    )


# ------------------------------------------------------------------------------------------------
# claim / bulk actions
#
# The convenor per-class ticket dashboard (design 3a) lives in the convenor blueprint as a pane
# (convenor.tickets_tab) so it renders inside the shared per-class dashboard chrome. This module
# keeps the shared, scope-agnostic actions used from there and from the ledger.


@tickets.route("/<int:ticket_id>/claim", methods=["POST"])
@login_required
def claim(ticket_id):
    ticket = Ticket.query.get(ticket_id)
    if ticket is None:
        abort(404)
    if not can_assign(current_user, ticket):
        abort(403)

    form = ConfirmActionForm()
    if form.validate_on_submit():
        assign(ticket, current_user, actor=current_user)
        try:
            log_db_commit(
                f"Claimed ticket #{ticket.id}",
                user=current_user,
                project_classes=list(ticket.scope_classes),
            )
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=exc)
            flash("Could not claim the ticket due to a database error.", "error")

    return redirect(redirect_url() or url_for("tickets.inbox"))


# ------------------------------------------------------------------------------------------------
# bulk actions (5b)


@tickets.route("/bulk", methods=["POST"])
@login_required
def bulk():
    form = ConfirmActionForm()
    if not form.validate_on_submit():
        abort(400)

    ids = request.form.getlist("ids", type=int)
    action = request.form.get("action", "")
    if not ids:
        flash("No tickets were selected.", "info")
        return redirect(redirect_url() or url_for("tickets.inbox"))

    label_id = request.form.get("label_id", type=int)
    status = request.form.get("status", type=int)
    label = Label.query.get(label_id) if label_id is not None else None

    applied = 0
    for ticket in Ticket.query.filter(Ticket.id.in_(ids)).all():
        if action == "add_label" and label is not None and label.tenant_id == ticket.tenant_id and can_label(current_user, ticket):
            add_label(ticket, label, actor=current_user)
            applied += 1
        elif action == "remove_label" and label is not None and can_label(current_user, ticket):
            remove_label(ticket, label, actor=current_user)
            applied += 1
        elif action == "set_status" and status in Ticket._labels and can_change_status(current_user, ticket):
            change_status(ticket, status, actor=current_user)
            applied += 1
        elif action == "assign_me" and can_assign(current_user, ticket):
            assign(ticket, current_user, actor=current_user)
            applied += 1
        elif action == "unassign" and can_assign(current_user, ticket):
            unassign(ticket, actor=current_user)
            applied += 1

    if applied > 0:
        try:
            log_db_commit(f"Bulk action '{action}' applied to {applied} ticket(s)", user=current_user)
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=exc)
            flash("Could not apply the bulk action due to a database error.", "error")
            return redirect(redirect_url() or url_for("tickets.inbox"))
        flash(f"Applied to {applied} ticket(s).", "info")
    else:
        flash("No changes applied — you may not have permission on the selected tickets.", "info")

    return redirect(redirect_url() or url_for("tickets.inbox"))
