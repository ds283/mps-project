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
Ticket detail view (design screen 2a) and its POST actions, plus the assign picker (4a). The view
is shared by all roles; per-ticket permission is enforced through the service-layer predicates
(app/shared/tickets/permissions.py), not a blanket role gate.
"""

from datetime import datetime

from flask import abort, current_app, flash, jsonify, redirect, request, url_for
from flask_security import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from app.tickets import tickets

from ..database import db
from ..models import (
    Label,
    ProjectClass,
    Role,
    SubmissionRole,
    Ticket,
    TicketEvent,
    TicketExternalSubscriber,
    TicketSubject,
    TicketSubjectTombstone,
    User,
)
from ..shared.context.convenor_dashboard import get_convenor_dashboard_data
from ..shared.context.faculty_dashboard import get_faculty_dashboard_data
from ..shared.context.global_context import render_template_context
from ..shared.context.root_dashboard import get_root_dashboard_data
from ..shared.forms.forms import ConfirmActionForm
from ..shared.tickets import (
    add_comment,
    add_external_subscriber,
    add_label,
    add_subject,
    admin_root_users_for,
    assign,
    authorized,
    can_assign,
    can_change_status,
    can_comment,
    can_edit_scope,
    can_label,
    can_manage_subscribers,
    can_view,
    candidates_for,
    change_status,
    convenors_in_scope,
    faculty_for_selecting_student,
    faculty_roles_for_submitting_student,
    is_subscribed,
    log_email,
    mark_read,
    remove_external_subscriber,
    remove_label,
    remove_subject,
    resolve_token,
    subscribe,
    unassign,
    unsubscribe,
)
from ..shared.workflow_logging import log_db_commit
from .forms import TicketCommentForm, TicketExternalSubscriberForm, TicketLogEmailForm, TicketSubjectAddForm

# events already represented in the thread as rich cards (or as the header) are hidden from the
# inline timeline; they still appear in the side-panel actions log.
_TIMELINE_HIDDEN = {TicketEvent.OPENED, TicketEvent.COMMENT_ADDED, TicketEvent.EMAIL_LOGGED}


def _load_ticket(ticket_id: int) -> Ticket:
    ticket = Ticket.query.get(ticket_id)
    if ticket is None:
        abort(404)
    return ticket


def _scope_pclasses(ticket):
    return list(ticket.scope_classes)


def _uname(user_id):
    if user_id is None:
        return "someone"
    user = User.query.get(user_id)
    return user.name if user is not None else "a former user"


def _describe_event(event: TicketEvent) -> dict:
    """Render an event as an icon + human sentence for the timeline / actions log."""
    payload = event.payload or {}
    kind = event.kind

    if kind == TicketEvent.STATUS_CHANGED:
        return {
            "icon": "flag",
            "text": "changed status",
            "kind": "status_changed",
            "from_status": payload.get("from"),
            "to_status": payload.get("to"),
        }

    if kind == TicketEvent.ASSIGNED:
        to = _uname(payload.get("to"))
        frm = payload.get("from")
        if payload.get("auto"):
            return {"icon": "user-check", "text": f"auto-assigned to {to}", "kind": "generic"}
        if frm is not None:
            return {
                "icon": "user-check",
                "text": "reassigned",
                "kind": "reassigned",
                "from_user": User.query.get(frm),
                "to_user": User.query.get(payload.get("to")),
            }
        return {"icon": "user-check", "text": f"assigned to {to}", "kind": "generic"}

    if kind == TicketEvent.UNASSIGNED:
        return {"icon": "user-slash", "text": "unassigned this ticket", "kind": "generic"}

    if kind == TicketEvent.LABEL_ADDED:
        label = Label.query.get(payload["label"]) if payload.get("label") else None
        name = payload.get("name", "")
        return {"icon": "tag", "text": f"added label {name}", "kind": "label", "added": True, "labels": [label], "label_names": [name]}

    if kind == TicketEvent.LABEL_REMOVED:
        label = Label.query.get(payload["label"]) if payload.get("label") else None
        name = payload.get("name", "")
        return {"icon": "tag", "text": f"removed label {name}", "kind": "label", "added": False, "labels": [label], "label_names": [name]}

    if kind == TicketEvent.SUBSCRIBED:
        who = payload.get("email") or _uname(payload.get("user"))
        return {"icon": "eye", "text": f"subscribed {who}", "kind": "generic"}

    if kind == TicketEvent.UNSUBSCRIBED:
        who = payload.get("email") or _uname(payload.get("user"))
        return {"icon": "eye-slash", "text": f"unsubscribed {who}", "kind": "generic"}

    if kind == TicketEvent.SUBJECT_ADDED:
        return {"icon": "link", "text": "added a subject", "kind": "generic"}

    if kind == TicketEvent.SUBJECT_REMOVED:
        return {"icon": "unlink", "text": "removed a subject", "kind": "generic"}

    if kind == TicketEvent.SUBJECT_TOMBSTONED:
        return {"icon": "user-slash", "text": "a linked student record was deleted", "kind": "generic"}

    return {"icon": "circle", "text": event.kind_label, "kind": "generic"}


def _build_timeline(ticket):
    """Merge comments, logged emails and non-hidden events into one chronological list."""
    items = []

    for comment in ticket.comments:
        items.append({"type": "comment", "when": comment.created_at, "obj": comment})

    for email in ticket.emails:
        items.append({"type": "email", "when": email.logged_at, "obj": email})

    for event in ticket.events:
        if event.kind in _TIMELINE_HIDDEN:
            continue
        entry = {"type": "event", "when": event.created_at, "obj": event}
        entry.update(_describe_event(event))
        items.append(entry)

    items.sort(key=lambda it: it["when"] or datetime.min)

    # coalesce consecutive label-add events by the same actor into a single "added labels" row so
    # the timeline reads like the reference design (grouped, coloured chips) rather than one row
    # per label.
    merged = []
    for it in items:
        prev = merged[-1] if merged else None
        if (
            it.get("kind") == "label"
            and it.get("added")
            and prev is not None
            and prev.get("kind") == "label"
            and prev.get("added")
            and prev["obj"].actor_id == it["obj"].actor_id
        ):
            prev["labels"] = prev.get("labels", []) + it.get("labels", [])
            prev["label_names"] = prev.get("label_names", []) + it.get("label_names", [])
            prev["when"] = it["when"]
        else:
            merged.append(it)
    return merged


# how many events to show in the side-panel actions log before it is truncated, to keep the rail
# within bounds on long-lived tickets.
_ACTIONS_LOG_LIMIT = 12


def _actions_log(ticket):
    """The most recent events, newest first, for the side-panel actions log (capped)."""
    log = []
    for event in ticket.events.order_by(TicketEvent.created_at.desc()).limit(_ACTIONS_LOG_LIMIT):
        entry = {"obj": event}
        entry.update(_describe_event(event))
        log.append(entry)
    return log


# role -> note-builder. Supervisor roles name the project when known; marker/moderator notes never
# name the project, to avoid any suggestion of a marking-anonymity leak in the picker UI.
_ROLE_NOTES = {
    SubmissionRole.ROLE_SUPERVISOR: lambda project: f"Supervises {project.name}" if project is not None else "Supervises their project",
    SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR: lambda project: f"Supervises {project.name}" if project is not None else "Supervises their project",
    SubmissionRole.ROLE_MARKER: lambda project: "Marks their submission",
    SubmissionRole.ROLE_MODERATOR: lambda project: "Moderates their submission",
}


def _related_faculty_for(ticket):
    """Faculty related to the ticket's student subjects, for the assign/subscribe pickers:
    supervisors/markers/moderators of a SUBMITTING_STUDENT subject (via SubmissionRole on any of
    their submission records), and the owning faculty member of a live sign-off request for a
    SELECTING_STUDENT subject (via ConfirmRequest). A person related through more than one
    relationship gets a single row with all notes/details joined. `note` is the assign-picker's
    project-focused text; `detail` is the subscribe-picker's relationship-focused text (student
    name, selector/submitter, role, and submission period when the project class has more than
    one)."""
    related = {}

    def _add(user, note, detail):
        if user is None:
            return
        entry = related.setdefault(user.id, {"user": user, "notes": [], "details": []})
        if note not in entry["notes"]:
            entry["notes"].append(note)
        if detail not in entry["details"]:
            entry["details"].append(detail)

    for subject in ticket.subjects:
        target = subject.target
        if target is None or isinstance(target, TicketSubjectTombstone):
            continue

        if subject.kind == TicketSubject.SUBMITTING_STUDENT:
            student_name = _student_name(target)
            config = getattr(target, "config", None)
            show_period = config is not None and config.number_submissions > 1

            for user, role, record in faculty_roles_for_submitting_student(target):
                note_builder = _ROLE_NOTES.get(role.role)
                if note_builder is None:
                    continue
                detail_parts = [student_name, "Submitter", role.role_as_str]
                period = getattr(record, "period", None)
                if show_period and period is not None:
                    detail_parts.append(period.display_name)
                _add(user, note_builder(getattr(record, "project", None)), " · ".join(detail_parts))

        elif subject.kind == TicketSubject.SELECTING_STUDENT:
            student_name = _student_name(target)
            for user, project in faculty_for_selecting_student(target):
                _add(user, f"Owns {project.name} (sign-off request)", f"{student_name} · Selector")

    return [{"user": entry["user"], "note": "; ".join(entry["notes"]), "detail": "; ".join(entry["details"])} for entry in related.values()]


def _office_users(ticket):
    query = User.query.filter(User.roles.any(Role.name == "office"))
    if ticket.tenant_id is not None:
        from ..models import Tenant

        query = query.filter(User.tenants.any(Tenant.id == ticket.tenant_id))
    return query.order_by(User.last_name.asc()).limit(25).all()


def _management_watchers(ticket):
    query = User.query.filter(User.roles.any(Role.name == "ticket_subscriber"))
    if ticket.tenant_id is not None:
        from ..models import Tenant

        query = query.filter(User.tenants.any(Tenant.id == ticket.tenant_id))
    return query.order_by(User.last_name.asc()).limit(25).all()


def _current_user_convened_class(ticket):
    """The name of an in-scope class current_user convenes, or None."""
    faculty = getattr(current_user, "faculty_data", None)
    if faculty is None:
        return None
    for pclass in ticket.scope_classes:
        if pclass.is_convenor(faculty.id):
            return pclass.name
    return None


def _build_assign_options(ticket):
    """Assemble the assign picker (screen 4a). Each user appears once, in its first section."""
    seen = set()
    sections = []

    def _section(title, rows_source, note=None):
        rows = []
        for entry in rows_source:
            user, row_note = (entry["user"], entry.get("note")) if isinstance(entry, dict) else (entry, note)
            if user is None or user.id in seen:
                continue
            seen.add(user.id)
            rows.append({"user": user, "note": row_note})
        if rows:
            sections.append({"title": title, "rows": rows})

    convened_class = _current_user_convened_class(ticket)
    if convened_class is not None:
        seen.add(current_user.id)
        is_current = ticket.assignee_id == current_user.id
        sections.append(
            {
                "title": "Suggested",
                "suggested": True,
                "rows": [
                    {
                        "user": current_user,
                        "note": f"Convenes {convened_class}",
                        "pill": "current · auto" if is_current else None,
                    }
                ],
            }
        )

    _section("Convenors in scope", convenors_in_scope(ticket))
    _section("Administrators", admin_root_users_for(ticket))
    _section("Related faculty", _related_faculty_for(ticket))
    _section("Office", _office_users(ticket))
    return sections


def _build_subscriber_options(ticket):
    """Assemble the subscriber "add" picker. Already-subscribed users are excluded so the list only
    shows addable people."""
    already = {sub.user_id for sub in ticket.subscriptions}
    seen = set(already)
    sections = []

    def _section(title, rows_source):
        rows = []
        for entry in rows_source:
            user, detail = (entry["user"], entry.get("detail")) if isinstance(entry, dict) else (entry, None)
            if user is None or user.id in seen:
                continue
            seen.add(user.id)
            rows.append({"user": user, "note": detail})
        if rows:
            sections.append({"title": title, "rows": rows})

    _section("Convenors in scope", convenors_in_scope(ticket))
    _section("Administrators", admin_root_users_for(ticket))
    _section("Related faculty", _related_faculty_for(ticket))
    _section("Office", _office_users(ticket))
    _section("Management watchers", _management_watchers(ticket))
    return sections


def _student_name(student):
    data = getattr(student, "student", None)
    user = getattr(data, "user", None)
    return user.name if user is not None else "Student"


_TOMBSTONE_LABELS = {
    TicketSubject.SUBMITTING_STUDENT: "Submitter (deleted)",
    TicketSubject.SELECTING_STUDENT: "Selector (deleted)",
}


def _subjects_display(ticket):
    """Resolve each subject to a display row {label, name, icon, url?} for the Context section. A
    tombstoned subject (its linked student has since been deleted) renders with the snapshot label
    captured at deletion time, a muted icon, and no link."""
    faculty = getattr(current_user, "faculty_data", None)
    convened = set()
    if faculty is not None:
        convened = {p.id for p in faculty.convenor_for} | {p.id for p in faculty.coconvenor_for}

    rows = []
    for subject in ticket.subjects:
        target = subject.target

        if isinstance(target, TicketSubjectTombstone):
            rows.append(
                {
                    "id": subject.id,
                    "label": _TOMBSTONE_LABELS.get(target.kind, "Deleted"),
                    "name": target.label,
                    "icon": "user-slash",
                    "url": None,
                    "tombstoned": True,
                }
            )
        elif subject.kind == TicketSubject.PROJECT_CLASS and target is not None:
            url = url_for("convenor.tickets_tab", id=target.id) if target.id in convened else None
            rows.append({"id": subject.id, "label": "Class", "name": target.name, "icon": "layer-group", "url": url})
        elif subject.kind == TicketSubject.SUBMITTING_STUDENT and target is not None:
            rows.append({"id": subject.id, "label": "Submitter", "name": _student_name(target), "icon": "user"})
        elif subject.kind == TicketSubject.SELECTING_STUDENT and target is not None:
            rows.append({"id": subject.id, "label": "Selector", "name": _student_name(target), "icon": "user-graduate"})
    return rows


def _scope_label(ticket):
    """A one-word scope descriptor for the Context section."""
    kinds = {subject.kind for subject in ticket.subjects}
    if TicketSubject.PROJECT_CLASS in kinds:
        return "Project class"
    if TicketSubject.SUBMITTING_STUDENT in kinds or TicketSubject.SELECTING_STUDENT in kinds:
        return "Student"
    return "General"


def _context_meta(ticket):
    """Icon-led Scope / Opened / Due rows for the Context section (matches reference screen 2a)."""
    opened = ticket.creation_timestamp
    due = ticket.due_date
    return [
        {"icon": "sitemap", "label": "Scope", "value": _scope_label(ticket)},
        {"icon": "calendar-alt", "label": "Opened", "value": opened.strftime("%d %b %Y") if opened else "—"},
        {"icon": "clock", "label": "Due", "value": due.strftime("%d %b %Y") if due else "—"},
    ]


def _available_labels(ticket):
    if ticket.tenant_id is None:
        return []
    applied = {label.id for label in ticket.labels}
    return [label for label in Label.query.filter_by(tenant_id=ticket.tenant_id).order_by(Label.name.asc()).all() if label.id not in applied]


def _safe_local(url):
    """Accept only a local, same-site path (open-redirect guard); otherwise return None."""
    if url and url.startswith("/") and not url.startswith("//"):
        return url
    return None


def _breadcrumb(ticket, return_url=None):
    """Breadcrumb data for the detail header. The 'Tickets' root returns the user to wherever they
    opened the ticket from (`return_url`, threaded via the canonical `url` query param from the
    inbox / ledger link, validated as a local path). When no return URL is supplied it falls back
    to a convenor ledger for an in-scope class the user convenes, else the personal inbox. Class
    crumbs always link to the convenor ledger for classes the user convenes."""
    faculty = getattr(current_user, "faculty_data", None)
    convened = set()
    if faculty is not None:
        convened = {p.id for p in faculty.convenor_for} | {p.id for p in faculty.coconvenor_for}

    classes = []
    ledger_url = None
    for pclass in ticket.scope_classes:
        url = url_for("convenor.tickets_tab", id=pclass.id) if pclass.id in convened else None
        classes.append({"name": pclass.name, "url": url})
        if ledger_url is None and url is not None:
            ledger_url = url

    home_url = _safe_local(return_url) or ledger_url or url_for("tickets.inbox")
    return {"home_url": home_url, "classes": classes}


def _origin_pclass(ticket):
    """Resolve the `pclass` query arg to a ProjectClass, but only if it is in this ticket's scope
    AND the current user convenes/co-convenes it. This is the entitlement guard for the convenor
    chrome — an untrusted `pclass` for a class the user does not convene returns None."""
    pclass_id = request.args.get("pclass", type=int)
    if pclass_id is None:
        return None

    faculty = getattr(current_user, "faculty_data", None)
    if faculty is None:
        return None
    convened = {p.id for p in faculty.convenor_for} | {p.id for p in faculty.coconvenor_for}
    if pclass_id not in convened:
        return None

    if not any(pclass.id == pclass_id for pclass in ticket.scope_classes):
        return None

    return ProjectClass.query.get(pclass_id)


def _detail_template(ticket):
    """Pick the per-surface wrapper template + its nav context from the `origin` the inbound link
    carried. Falls back to the bare tickets/detail.html chrome when the origin is absent or the
    current user is not entitled to the requested chrome. Office is deferred until an office nav
    base exists."""
    origin = request.args.get("origin")

    if origin == "convenor":
        pclass = _origin_pclass(ticket)
        if pclass is not None:
            config = pclass.most_recent_config
            if config is not None:
                return "tickets/convenor_detail.html", {
                    "pane": "tickets",
                    "pclass": pclass,
                    "config": config,
                    "convenor_data": get_convenor_dashboard_data(pclass, config),
                }

    elif origin == "faculty" and current_user.has_role("faculty"):
        nav_ctx = {"pane": "tickets", **get_faculty_dashboard_data(current_user)}
        if current_user.has_role("root"):
            nav_ctx["root_dash_data"] = get_root_dashboard_data()
        return "faculty/dashboard/faculty_detail.html", nav_ctx

    return "tickets/detail.html", {}


# ------------------------------------------------------------------------------------------------
# views


@tickets.route("/<int:ticket_id>")
@login_required
def detail(ticket_id):
    ticket = _load_ticket(ticket_id)
    if not can_view(current_user, ticket):
        abort(403)

    mark_read(ticket, current_user)
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=exc)

    template, nav_ctx = _detail_template(ticket)
    return render_template_context(
        template,
        **nav_ctx,
        ticket=ticket,
        breadcrumb=_breadcrumb(ticket, request.args.get("url")),
        timeline=_build_timeline(ticket),
        actions_log=_actions_log(ticket),
        assign_sections=_build_assign_options(ticket),
        subjects=_subjects_display(ticket),
        context_meta=_context_meta(ticket),
        subscribers=list(ticket.subscriptions),
        external_subscribers=list(ticket.external_subscribers),
        subscriber_sections=_build_subscriber_options(ticket),
        available_labels=_available_labels(ticket),
        all_statuses=[(value, label) for value, label in Ticket._labels.items()],
        watching=is_subscribed(current_user, ticket),
        comment_form=TicketCommentForm(),
        email_form=TicketLogEmailForm(),
        action_form=ConfirmActionForm(),
        external_form=TicketExternalSubscriberForm(),
        subject_add_form=TicketSubjectAddForm(),
        perms={
            "comment": can_comment(current_user, ticket),
            "status": can_change_status(current_user, ticket),
            "assign": can_assign(current_user, ticket),
            "label": can_label(current_user, ticket),
            "subscribe": can_manage_subscribers(current_user, ticket),
            "edit_scope": can_edit_scope(current_user, ticket),
        },
    )


def _commit_or_flash(summary, ticket, failure_message):
    """Commit via log_db_commit, or roll back and flash on database error. Returns success bool."""
    try:
        log_db_commit(summary, user=current_user, project_classes=_scope_pclasses(ticket))
        return True
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=exc)
        flash(failure_message, "error")
        return False


def _back(ticket):
    return redirect(url_for("tickets.detail", ticket_id=ticket.id))


@tickets.route("/<int:ticket_id>/comment", methods=["POST"])
@login_required
def comment(ticket_id):
    ticket = _load_ticket(ticket_id)
    if not can_comment(current_user, ticket):
        abort(403)

    form = TicketCommentForm()
    if form.validate_on_submit():
        new_comment = add_comment(ticket, current_user, form.body.data, actor=current_user)
        resolve = form.submit_resolve.data
        if resolve and can_change_status(current_user, ticket):
            change_status(ticket, Ticket.RESOLVED, actor=current_user)
        committed = _commit_or_flash(
            f"Commented on ticket #{ticket.id}" + (" and resolved it" if resolve else ""),
            ticket,
            "Could not post comment due to a database error. Please contact a system administrator.",
        )
        if committed and form.notify.data:
            _notify_subscribers(ticket, new_comment)
    else:
        flash("Your comment could not be posted — please enter some text.", "error")

    return _back(ticket)


def _notify_subscribers(ticket, comment):
    """Enqueue the subscriber email fan-out for a new comment."""
    celery = current_app.extensions["celery"]
    ticket_url = url_for("tickets.detail", ticket_id=ticket.id, _external=True)
    settings_url = url_for("tickets.inbox", _external=True)
    try:
        celery.tasks["app.tasks.ticket_notifications.send_ticket_comment_notifications"].apply_async(
            args=(ticket.id, comment.id, current_user.id, ticket_url, settings_url)
        )
    except Exception as exc:
        current_app.logger.exception("Failed to enqueue ticket comment notification", exc_info=exc)


@tickets.route("/<int:ticket_id>/log_email", methods=["POST"])
@login_required
def log_email_action(ticket_id):
    ticket = _load_ticket(ticket_id)
    if not can_comment(current_user, ticket):
        abort(403)

    form = TicketLogEmailForm()
    if form.validate_on_submit():
        log_email(
            ticket,
            direction=form.direction.data,
            subject=form.subject.data,
            body=form.body.data,
            from_addr=form.from_addr.data,
            to_addrs=form.to_addrs.data,
            logged_by=current_user,
            actor=current_user,
        )
        _commit_or_flash(
            f"Logged an email against ticket #{ticket.id}",
            ticket,
            "Could not log the email due to a database error. Please contact a system administrator.",
        )
    else:
        flash("The email could not be logged — a subject is required.", "error")

    return _back(ticket)


@tickets.route("/<int:ticket_id>/status/<int:status>", methods=["POST"])
@login_required
def set_status(ticket_id, status):
    ticket = _load_ticket(ticket_id)
    if not can_change_status(current_user, ticket):
        abort(403)
    if status not in Ticket._labels:
        abort(404)

    form = ConfirmActionForm()
    if form.validate_on_submit():
        change_status(ticket, status, actor=current_user)
        _commit_or_flash(
            f"Set status of ticket #{ticket.id} to {Ticket._labels[status]}",
            ticket,
            "Could not update the ticket status due to a database error.",
        )

    return _back(ticket)


@tickets.route("/<int:ticket_id>/assign/<int:user_id>", methods=["POST"])
@login_required
def assign_to(ticket_id, user_id):
    ticket = _load_ticket(ticket_id)
    if not can_assign(current_user, ticket):
        abort(403)

    target = User.query.get(user_id)
    if target is None:
        abort(404)

    form = ConfirmActionForm()
    if form.validate_on_submit():
        assign(ticket, target, actor=current_user)
        _commit_or_flash(
            f"Assigned ticket #{ticket.id} to {target.name}",
            ticket,
            "Could not assign the ticket due to a database error.",
        )

    return _back(ticket)


@tickets.route("/<int:ticket_id>/unassign", methods=["POST"])
@login_required
def unassign_ticket(ticket_id):
    ticket = _load_ticket(ticket_id)
    if not can_assign(current_user, ticket):
        abort(403)

    form = ConfirmActionForm()
    if form.validate_on_submit():
        unassign(ticket, actor=current_user)
        _commit_or_flash(
            f"Unassigned ticket #{ticket.id}",
            ticket,
            "Could not unassign the ticket due to a database error.",
        )

    return _back(ticket)


@tickets.route("/<int:ticket_id>/label/add/<int:label_id>", methods=["POST"])
@login_required
def label_add(ticket_id, label_id):
    ticket = _load_ticket(ticket_id)
    if not can_label(current_user, ticket):
        abort(403)

    label = Label.query.get(label_id)
    if label is None or label.tenant_id != ticket.tenant_id:
        abort(404)

    form = ConfirmActionForm()
    if form.validate_on_submit():
        add_label(ticket, label, actor=current_user)
        _commit_or_flash(
            f"Added label '{label.name}' to ticket #{ticket.id}",
            ticket,
            "Could not add the label due to a database error.",
        )

    return _back(ticket)


@tickets.route("/<int:ticket_id>/label/remove/<int:label_id>", methods=["POST"])
@login_required
def label_remove(ticket_id, label_id):
    ticket = _load_ticket(ticket_id)
    if not can_label(current_user, ticket):
        abort(403)

    label = Label.query.get(label_id)
    if label is None:
        abort(404)

    form = ConfirmActionForm()
    if form.validate_on_submit():
        remove_label(ticket, label, actor=current_user)
        _commit_or_flash(
            f"Removed label '{label.name}' from ticket #{ticket.id}",
            ticket,
            "Could not remove the label due to a database error.",
        )

    return _back(ticket)


@tickets.route("/<int:ticket_id>/watch", methods=["POST"])
@login_required
def watch(ticket_id):
    ticket = _load_ticket(ticket_id)
    if not can_view(current_user, ticket):
        abort(403)

    form = ConfirmActionForm()
    if form.validate_on_submit():
        subscribe(ticket, current_user, actor=current_user)
        _commit_or_flash(
            f"Subscribed to ticket #{ticket.id}",
            ticket,
            "Could not subscribe due to a database error.",
        )

    return _back(ticket)


@tickets.route("/<int:ticket_id>/unwatch", methods=["POST"])
@login_required
def unwatch(ticket_id):
    ticket = _load_ticket(ticket_id)
    if not can_view(current_user, ticket):
        abort(403)

    form = ConfirmActionForm()
    if form.validate_on_submit():
        unsubscribe(ticket, current_user, actor=current_user)
        _commit_or_flash(
            f"Unsubscribed from ticket #{ticket.id}",
            ticket,
            "Could not unsubscribe due to a database error.",
        )

    return _back(ticket)


@tickets.route("/<int:ticket_id>/subscriber/add/<int:user_id>", methods=["POST"])
@login_required
def subscriber_add(ticket_id, user_id):
    ticket = _load_ticket(ticket_id)
    if not can_manage_subscribers(current_user, ticket):
        abort(403)

    target = User.query.get(user_id)
    if target is None:
        abort(404)

    form = ConfirmActionForm()
    if form.validate_on_submit():
        subscribe(ticket, target, actor=current_user)
        _commit_or_flash(
            f"Added {target.name} as a subscriber to ticket #{ticket.id}",
            ticket,
            "Could not add the subscriber due to a database error.",
        )

    return _back(ticket)


@tickets.route("/<int:ticket_id>/subscriber/remove/<int:user_id>", methods=["POST"])
@login_required
def subscriber_remove(ticket_id, user_id):
    ticket = _load_ticket(ticket_id)
    if not can_manage_subscribers(current_user, ticket):
        abort(403)

    target = User.query.get(user_id)
    if target is None:
        abort(404)

    form = ConfirmActionForm()
    if form.validate_on_submit():
        unsubscribe(ticket, target, actor=current_user)
        _commit_or_flash(
            f"Removed {target.name} as a subscriber from ticket #{ticket.id}",
            ticket,
            "Could not remove the subscriber due to a database error.",
        )

    return _back(ticket)


@tickets.route("/<int:ticket_id>/external_subscriber/add", methods=["POST"])
@login_required
def external_subscriber_add(ticket_id):
    ticket = _load_ticket(ticket_id)
    if not can_manage_subscribers(current_user, ticket):
        abort(403)

    form = TicketExternalSubscriberForm()
    if form.validate_on_submit():
        add_external_subscriber(ticket, form.email.data, actor=current_user)
        _commit_or_flash(
            f"Added {form.email.data} as a subscriber to ticket #{ticket.id}",
            ticket,
            "Could not add the subscriber due to a database error.",
        )
    else:
        flash("Could not add the subscriber — please enter a valid email address.", "error")

    return _back(ticket)


@tickets.route("/<int:ticket_id>/external_subscriber/remove/<int:ext_id>", methods=["POST"])
@login_required
def external_subscriber_remove(ticket_id, ext_id):
    ticket = _load_ticket(ticket_id)
    if not can_manage_subscribers(current_user, ticket):
        abort(403)

    external = TicketExternalSubscriber.query.get(ext_id)
    if external is None or external.ticket_id != ticket.id:
        abort(404)

    form = ConfirmActionForm()
    if form.validate_on_submit():
        remove_external_subscriber(ticket, external, actor=current_user)
        _commit_or_flash(
            f"Removed {external.email} as a subscriber from ticket #{ticket.id}",
            ticket,
            "Could not remove the subscriber due to a database error.",
        )

    return _back(ticket)


@tickets.route("/<int:ticket_id>/subject/people")
@login_required
def subject_people(ticket_id):
    """select2 remote data source for the "add subject" picker on the detail view — the same
    origin-scoped candidate engine as compose, keyed off the page's own origin/pclass context."""
    ticket = _load_ticket(ticket_id)
    if not can_edit_scope(current_user, ticket):
        abort(403)

    query_term = (request.args.get("q") or "").strip()
    convenor_pclass = _origin_pclass(ticket)
    origin = "convenor" if convenor_pclass is not None else request.args.get("origin")
    groups = candidates_for(
        current_user,
        query_term,
        origin=origin,
        pclass_id=convenor_pclass.id if convenor_pclass is not None else None,
    )
    return jsonify({"results": groups})


@tickets.route("/<int:ticket_id>/subject/add", methods=["POST"])
@login_required
def subject_add(ticket_id):
    ticket = _load_ticket(ticket_id)
    if not can_edit_scope(current_user, ticket):
        abort(403)

    form = TicketSubjectAddForm()
    if form.validate_on_submit():
        convenor_pclass = _origin_pclass(ticket)
        resolved = resolve_token(form.token.data)
        if resolved is None or not authorized(current_user, *resolved, convenor_pclass=convenor_pclass):
            flash("That subject is invalid or outside your permitted scope.", "error")
        else:
            kind, target = resolved
            add_subject(ticket, kind, target, actor=current_user)
            _commit_or_flash(
                f"Added a subject to ticket #{ticket.id}",
                ticket,
                "Could not add the subject due to a database error.",
            )
    else:
        flash("Could not add the subject — please choose one from the picker.", "error")

    return _back(ticket)


@tickets.route("/<int:ticket_id>/subject/remove/<int:subject_id>", methods=["POST"])
@login_required
def subject_remove(ticket_id, subject_id):
    ticket = _load_ticket(ticket_id)
    if not can_edit_scope(current_user, ticket):
        abort(403)

    subject = TicketSubject.query.get(subject_id)
    if subject is None or subject.ticket_id != ticket.id:
        abort(404)

    form = ConfirmActionForm()
    if form.validate_on_submit():
        if remove_subject(ticket, subject, actor=current_user):
            _commit_or_flash(
                f"Removed a subject from ticket #{ticket.id}",
                ticket,
                "Could not remove the subject due to a database error.",
            )
        else:
            flash("A ticket must keep at least one scoping subject.", "error")

    return _back(ticket)
