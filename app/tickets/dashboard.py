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

from datetime import datetime, timedelta

from flask import abort, current_app, flash, redirect, request, url_for
from flask_security import current_user, login_required
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError

import app.ajax as ajax
from app.tickets import tickets
from .detail import _describe_event
from ..database import db
from ..models import Label, ProjectClass, Ticket, TicketComment, TicketEmail, TicketEvent, TicketReadState, TicketSubject, TicketSubscription
from ..shared.context.global_context import render_template_context
from ..shared.forms.forms import ConfirmActionForm
from ..shared.tickets import (
    add_label,
    assign,
    can_assign,
    can_change_status,
    can_label,
    change_status,
    record_inbox_visit,
    remove_label,
    resolve_token as _resolve_token,
    student_name as _student_name,
    unassign,
)
from ..shared.utils import redirect_url
from ..shared.workflow_logging import log_db_commit

# events already shown as rich cards elsewhere in the feed (comment/email rows), matching the
# ticket-detail timeline's own hidden set (app/tickets/detail.py:_TIMELINE_HIDDEN)
_FEED_HIDDEN_EVENTS = {TicketEvent.OPENED, TicketEvent.COMMENT_ADDED, TicketEvent.EMAIL_LOGGED}

# rail views for the personal inbox (2c): (key, label, icon)
INBOX_VIEWS = [
    ("all_open", "All open", "inbox"),
    ("assigned", "Assigned to me", "user-check"),
    ("watching", "Watching", "eye"),
    ("unread", "Unread", "bell"),
    ("created", "Created by me", "pen"),
    ("closed", "Closed", "check-circle"),
]


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


def _watched_condition(user):
    return Ticket.subscriptions.any(TicketSubscription.user_id == user.id)


def _my_universe_condition(user):
    """Every ticket that belongs in the user's personal inbox: assigned, watched, or opened by them."""
    return or_(Ticket.assignee_id == user.id, Ticket.creator_id == user.id, _watched_condition(user))


def _unread_condition(user):
    """A ticket is unread if edited since the caller's read marker (or never read) — except for
    the ticket's own creator, who never sees their own ticket as unread. See
    app.shared.tickets.read_state.is_unread(), which this mirrors in SQL for bulk filtering."""
    read_and_current = Ticket.read_states.any(and_(TicketReadState.user_id == user.id, TicketReadState.last_read_at >= Ticket.last_edit_timestamp))
    return and_(
        Ticket.last_edit_timestamp.isnot(None),
        or_(Ticket.creator_id.is_(None), Ticket.creator_id != user.id),
        ~read_and_current,
    )


def _mine_base_query(user, view: str):
    if view == "assigned":
        condition = Ticket.assignee_id == user.id
    elif view == "watching":
        condition = _watched_condition(user)
    elif view == "unread":
        condition = and_(_my_universe_condition(user), _unread_condition(user))
    elif view == "created":
        condition = Ticket.creator_id == user.id
    elif view == "closed":
        condition = and_(_my_universe_condition(user), Ticket.status == Ticket.CLOSED)
    else:  # "all_open"
        condition = and_(_my_universe_condition(user), Ticket.status.in_(Ticket.OPEN_STATES))
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

    kind = args.get("subject_kind")
    if kind == "submitter":
        query = query.filter(Ticket.subjects.any(TicketSubject.kind == TicketSubject.SUBMITTING_STUDENT))
    elif kind == "selector":
        query = query.filter(Ticket.subjects.any(TicketSubject.kind == TicketSubject.SELECTING_STUDENT))
    elif kind == "class":
        query = query.filter(or_(Ticket.subjects.any(TicketSubject.kind == TicketSubject.PROJECT_CLASS), ~Ticket.subjects.any()))

    token = args.get("subject")
    if token:
        resolved = _resolve_token(token)
        if resolved is not None:
            rkind, target = resolved
            if rkind == TicketSubject.SUBMITTING_STUDENT:
                query = query.filter(Ticket.subjects.any(submitting_student_id=target.id))
            elif rkind == TicketSubject.SELECTING_STUDENT:
                query = query.filter(Ticket.subjects.any(selecting_student_id=target.id))
            elif rkind == TicketSubject.PROJECT_CLASS:
                query = query.filter(Ticket.scope_classes.any(ProjectClass.id == target.id))

    return query


def _subject_label(token):
    """Human-readable label for an already-selected scope-filter token, so the select2 picker can
    re-render its current selection without an extra round-trip."""
    if not token:
        return None
    resolved = _resolve_token(token)
    if resolved is None:
        return None
    kind, target = resolved
    if kind == TicketSubject.PROJECT_CLASS:
        return f"{target.name}"
    return _student_name(target)


def _user_labels(user):
    """Labels visible to `user`, each annotated with `.inbox_count` — the number of tickets in the
    user's own inbox universe (assigned/watched/created) carrying that label."""
    tenant_ids = [tenant.id for tenant in user.tenants]
    if not tenant_ids:
        return []
    labels = Label.query.filter(Label.tenant_id.in_(tenant_ids)).order_by(Label.name.asc()).all()
    universe = _my_universe_condition(user)
    for label in labels:
        label.inbox_count = Ticket.query.filter(universe, Ticket.labels.any(Label.id == label.id)).count()
    return labels


# ------------------------------------------------------------------------------------------------
# AJAX ledger feed


@tickets.route("/ledger_ajax", methods=["GET", "POST"])
@login_required
def ledger_ajax():
    mode = request.args.get("mode", "mine")
    if mode == "convenor":
        class_id = request.args.get("class_id", type=int)
        base_query = _convenor_base_query(current_user, class_id)
        origin, pclass_id = "convenor", class_id
    else:
        base_query = _mine_base_query(current_user, request.args.get("view", "all_open"))
        # personal inbox threads no origin; the faculty inbox pane sets origin=faculty on its feed URL
        origin, pclass_id = request.args.get("origin"), None

    base_query = _apply_common_filters(base_query, request.args).order_by(Ticket.last_edit_timestamp.desc())
    return ajax.tickets.ledger_data(base_query, return_url=request.args.get("url"), origin=origin, pclass_id=pclass_id)


# ------------------------------------------------------------------------------------------------
# faculty / office inbox (2c)


def _newly_assigned_count(user, since):
    """Tickets currently assigned to `user` where the assignment happened after `since`."""
    if since is None:
        return 0
    ticket_ids = set()
    for event in TicketEvent.query.filter(TicketEvent.kind == TicketEvent.ASSIGNED, TicketEvent.created_at > since):
        payload = event.payload or {}
        if payload.get("to") == user.id:
            ticket_ids.add(event.ticket_id)
    if not ticket_ids:
        return 0
    return Ticket.query.filter(Ticket.id.in_(ticket_ids), Ticket.assignee_id == user.id).count()


def _new_comment_count(user, since):
    """Comments posted (by someone else) since `since` on tickets `user` watches."""
    if since is None:
        return 0
    return TicketComment.query.filter(
        TicketComment.ticket.has(_watched_condition(user)),
        TicketComment.created_at > since,
        TicketComment.author_id != user.id,
    ).count()


def _due_this_week(user):
    now = datetime.now()
    week_end = now + timedelta(days=7)
    query = Ticket.query.filter(
        _my_universe_condition(user),
        Ticket.status.in_(Ticket.OPEN_STATES),
        Ticket.due_date.isnot(None),
        Ticket.due_date >= now,
        Ticket.due_date <= week_end,
    ).order_by(Ticket.due_date.asc())
    return query.count(), query.first()


def _activity_feed(user, since, limit=10):
    """Recent events/comments/emails on tickets in `user`'s inbox universe, newest first, each
    flagged `is_new` if it postdates the caller's previous inbox visit."""
    universe = _my_universe_condition(user)
    ticket_ids = [tid for (tid,) in db.session.query(Ticket.id).filter(universe).all()]
    if not ticket_ids:
        return []

    fetch_limit = limit * 3
    items = []
    for event in (
            TicketEvent.query.filter(TicketEvent.ticket_id.in_(ticket_ids), ~TicketEvent.kind.in_(_FEED_HIDDEN_EVENTS))
                    .order_by(TicketEvent.created_at.desc())
                    .limit(fetch_limit)
    ):
        entry = {"kind": "event", "ticket_id": event.ticket_id, "when": event.created_at, "obj": event}
        entry.update(_describe_event(event))
        items.append(entry)
    for comment in TicketComment.query.filter(TicketComment.ticket_id.in_(ticket_ids)).order_by(TicketComment.created_at.desc()).limit(fetch_limit):
        items.append({"kind": "comment", "ticket_id": comment.ticket_id, "when": comment.created_at, "obj": comment})
    for email in TicketEmail.query.filter(TicketEmail.ticket_id.in_(ticket_ids)).order_by(TicketEmail.logged_at.desc()).limit(fetch_limit):
        items.append({"kind": "email", "ticket_id": email.ticket_id, "when": email.logged_at, "obj": email})

    items.sort(key=lambda it: it["when"] or datetime.min, reverse=True)
    items = items[:limit]

    tickets_by_id = {t.id: t for t in Ticket.query.filter(Ticket.id.in_({it["ticket_id"] for it in items})).all()}
    for item in items:
        item["ticket"] = tickets_by_id.get(item["ticket_id"])
        item["is_new"] = since is not None and item["when"] is not None and item["when"] > since
    return items


def build_inbox_context(user, args) -> dict:
    """
    Assemble the personal-inbox (design 2c) context for `user` from a request args mapping. Shared
    by the standalone tickets.inbox page and the faculty dashboard "My tickets" pane so both surfaces
    stay in lock-step. The ledger data itself is served separately by ledger_ajax (mode=mine).

    Records this call as the user's inbox visit (updating TicketInboxVisit), using the *previous*
    visit timestamp as the "since you last visited" cutoff for this render's metrics/Activity feed.
    """
    view = args.get("view", "all_open")
    view_keys = {key for key, _, _ in INBOX_VIEWS}
    if view not in view_keys:
        view = "all_open"

    previous_visit = record_inbox_visit(user)
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=exc)

    view_counts = {key: _mine_base_query(user, key).count() for key, _, _ in INBOX_VIEWS}

    due_count, nearest_due = _due_this_week(user)

    return {
        "view": view,
        "views": INBOX_VIEWS,
        "view_counts": view_counts,
        "labels": _user_labels(user),
        "selected_label": args.get("label_id", type=int),
        "selected_subject_kind": args.get("subject_kind"),
        "selected_subject": args.get("subject"),
        "selected_subject_label": _subject_label(args.get("subject")),
        "metrics": {
            "newly_assigned": _newly_assigned_count(user, previous_visit),
            "new_comments": _new_comment_count(user, previous_visit),
            "due_count": due_count,
            "due_nearest": nearest_due,
        },
        "activity": _activity_feed(user, previous_visit),
        "all_statuses": [(value, label) for value, label in Ticket._labels.items()],
    }


@tickets.route("/inbox")
@login_required
def inbox():
    return render_template_context("tickets/inbox.html", **build_inbox_context(current_user, request.args))


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
