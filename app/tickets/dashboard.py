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
Ticket dashboards: the faculty/office personal inbox (design screen 2c), the convenor triage
dashboard (3a), and the shared server-side ledger AJAX feed (1a). The ledger endpoint always
receives a permission-scoped base query built here; scope is never taken from the client.
"""

from datetime import datetime

from flask import abort, current_app, flash, redirect, request, url_for
from flask_security import current_user, login_required, roles_accepted
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

import app.ajax as ajax
from app.tickets import tickets

from ..database import db
from ..models import Label, ProjectClass, Ticket, TicketSubscription
from ..shared.context.global_context import render_template_context
from ..shared.forms.forms import ConfirmActionForm
from ..shared.tickets import assign, can_assign
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
# convenor dashboard (3a)


@tickets.route("/convenor")
@roles_accepted("faculty", "admin", "root")
def convenor_dashboard():
    faculty = getattr(current_user, "faculty_data", None)
    if not _is_admin_or_root(current_user) and (faculty is None or not faculty.is_convenor):
        flash("You do not convene any project classes.", "info")
        return redirect(url_for("tickets.inbox"))

    class_id = request.args.get("class_id", type=int)
    ids = _convened_class_ids(current_user)
    if class_id is not None and ids is not None and class_id not in ids:
        abort(403)

    # needs-triage: unassigned tickets in my scope that span more than one class
    triage_query = _convenor_base_query(current_user, class_id).filter(Ticket.assignee_id.is_(None))
    needs_triage = [t for t in triage_query.order_by(Ticket.last_edit_timestamp.desc()).all() if t.scope_classes.count() > 1]

    convened_classes = None
    if ids is not None:
        convened_classes = ProjectClass.query.filter(ProjectClass.id.in_(ids)).order_by(ProjectClass.name.asc()).all()

    return render_template_context(
        "tickets/convenor_dashboard.html",
        needs_triage=needs_triage,
        needs_triage_meta=[_triage_meta(t) for t in needs_triage],
        convened_classes=convened_classes,
        selected_class_id=class_id,
        labels=_user_labels(current_user),
        selected_label=request.args.get("label_id", type=int),
        selected_status=request.args.get("status", type=int),
        all_statuses=[(value, label) for value, label in Ticket._labels.items()],
        action_form=ConfirmActionForm(),
    )


def _triage_meta(ticket):
    classes = list(ticket.scope_classes)
    return {
        "id": ticket.id,
        "scope_names": [pclass.name for pclass in classes],
        "overdue": ticket.due_date is not None and ticket.status in Ticket.OPEN_STATES and ticket.due_date < datetime.now(),
    }


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

    return redirect(redirect_url() or url_for("tickets.convenor_dashboard"))
