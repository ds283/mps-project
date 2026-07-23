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
Subject management and ticket creation for the ticket service layer.

Adding or removing a subject re-derives the ticket's cached class scope and refreshes convenor
subscriptions. Adding a subject never steals an existing owner (spec decision 3): auto-assignment
only fires while the ticket is unassigned. None of these functions commit — the caller owns the
transaction (and should log via log_db_commit()).
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional, Tuple

from ...database import db
from ...models import Ticket, TicketEvent, TicketSubject, TicketSubjectTombstone, TicketSubscription
from .candidates import student_name
from .events import record_event
from .routing import apply_auto_assign
from .scope import recompute_scope
from .subscriptions import subscribe, sync_convenor_subscriptions

# subject kinds that can legitimately be tombstoned — a project class is never deleted through this
# path, only submitting/selecting students are.
_TOMBSTONABLE_KINDS = (TicketSubject.SUBMITTING_STUDENT, TicketSubject.SELECTING_STUDENT)

# maps a subject kind to the FK column that carries its target id
_KIND_FIELD = {
    TicketSubject.SUBMITTING_STUDENT: "submitting_student_id",
    TicketSubject.SELECTING_STUDENT: "selecting_student_id",
    TicketSubject.PROJECT_CLASS: "project_class_id",
}


def _make_subject(ticket, kind: int, target) -> TicketSubject:
    if kind not in _KIND_FIELD:
        raise ValueError(f"Unknown ticket subject kind: {kind}")
    subject = TicketSubject(ticket=ticket, kind=kind)
    setattr(subject, _KIND_FIELD[kind], target.id)
    return subject


def add_subject(ticket, kind: int, target, actor=None, reroute: bool = True) -> TicketSubject:
    """
    Attach a subject to a ticket, re-derive scope, refresh convenor subscriptions, and (if the
    ticket is still unassigned and reroute is True) apply the auto-assign rule.
    """
    subject = _make_subject(ticket, kind, target)
    db.session.add(subject)
    db.session.flush()

    record_event(ticket, actor, TicketEvent.SUBJECT_ADDED, {"kind": kind, "target": target.id})
    recompute_scope(ticket)
    sync_convenor_subscriptions(ticket, actor=actor)

    if reroute and ticket.assignee_id is None:
        apply_auto_assign(ticket, actor=actor)

    return subject


def remove_subject(ticket, subject: TicketSubject, actor=None) -> bool:
    """
    Detach a subject and re-derive scope. Never auto-unassigns; the current owner is kept.

    Refuses to remove a ticket's last remaining subject — a ticket must always keep at least one
    scoping object — and returns False (no-op) in that case rather than raising, so callers can
    flash a message. Returns True on success.
    """
    if ticket.subjects.count() <= 1:
        return False

    target = subject.target
    if isinstance(target, TicketSubjectTombstone):
        payload = {"kind": subject.kind, "label": target.label}
    else:
        payload = {"kind": subject.kind, "target": target.id if target is not None else None}
    db.session.delete(subject)
    db.session.flush()

    record_event(ticket, actor, TicketEvent.SUBJECT_REMOVED, payload)
    recompute_scope(ticket)
    return True


def create_ticket(
    *,
    title: str,
    opener,
    description: Optional[str] = None,
    subjects: Optional[Iterable[Tuple[int, object]]] = None,
    due_date=None,
    assignee=None,
    actor=None,
) -> Ticket:
    """
    Create a ticket end-to-end: open event, subjects, derived scope, auto-assign (only if no
    explicit assignee was given), and auto-subscriptions (opener, assignee, in-scope convenors).

    :param subjects: iterable of (kind, target) tuples, where kind is a TicketSubjectKindMixin
        constant and target is the SubmittingStudent / SelectingStudent / ProjectClass instance.
    """
    actor = actor if actor is not None else opener
    now = datetime.now()

    ticket = Ticket(
        title=title,
        description=description,
        status=Ticket.OPEN,
        creator_id=(opener.id if opener is not None else None),
        creation_timestamp=now,
        # last_edit_timestamp / last_edit_id are set by the OPENED event below (touch())
        due_date=due_date,
        assignee_id=(assignee.id if assignee is not None else None),
    )
    db.session.add(ticket)
    db.session.flush()

    record_event(ticket, actor, TicketEvent.OPENED, None)

    for kind, target in subjects or []:
        subject = _make_subject(ticket, kind, target)
        db.session.add(subject)
        record_event(ticket, actor, TicketEvent.SUBJECT_ADDED, {"kind": kind, "target": target.id})

    db.session.flush()
    recompute_scope(ticket)

    # auto-assign only when the caller did not pin an assignee
    if ticket.assignee_id is None:
        apply_auto_assign(ticket, actor=actor)

    if opener is not None:
        subscribe(ticket, opener, reason=TicketSubscription.OPENER, actor=actor)
    if ticket.assignee is not None:
        subscribe(ticket, ticket.assignee, reason=TicketSubscription.ASSIGNEE, actor=actor)
    sync_convenor_subscriptions(ticket, actor=actor)

    return ticket


def open_tickets_for_student(student, kind: int):
    """
    The open (OPEN_STATES) tickets that reference `student` via a live (non-tombstoned)
    TicketSubject of the given kind — used by the delete-submitter/delete-selector confirmation
    pages to warn that deleting the student will affect a ticket, before the deletion happens.
    """
    field = _KIND_FIELD.get(kind)
    if field is None or kind not in _TOMBSTONABLE_KINDS:
        raise ValueError(f"Cannot look up tickets for a subject of kind: {kind}")

    return (
        Ticket.query.join(TicketSubject, TicketSubject.ticket_id == Ticket.id)
        .filter(getattr(TicketSubject, field) == student.id, Ticket.status.in_(Ticket.OPEN_STATES))
        .distinct()
        .all()
    )


def tombstone_subjects_for_student(student, kind: int, actor=None) -> list[TicketSubject]:
    """
    Convert every TicketSubject referencing `student` (a SubmittingStudent or SelectingStudent about
    to be deleted) into a tombstone: capture its display name and the deletion time, then null the
    FK column so the subsequent delete of `student` no longer hits the FK constraint. `kind` is left
    unchanged on the subject — it still identifies what kind of link was lost (see
    `TicketSubject.target`). Never touches `ticket.assignee_id`, mirroring `add_subject` /
    `remove_subject`'s "never steals an existing owner" rule. Does not commit — the caller owns the
    transaction and should call this before deleting `student`.
    """
    field = _KIND_FIELD.get(kind)
    if field is None or kind not in _TOMBSTONABLE_KINDS:
        raise ValueError(f"Cannot tombstone a subject of kind: {kind}")

    subjects = TicketSubject.query.filter(getattr(TicketSubject, field) == student.id).all()
    if not subjects:
        return []

    label = student_name(student)
    now = datetime.now()

    for subject in subjects:
        setattr(subject, field, None)
        subject.deleted_snapshot_label = label
        subject.deleted_at = now

    db.session.flush()

    for subject in subjects:
        record_event(subject.ticket, actor, TicketEvent.SUBJECT_TOMBSTONED, {"kind": kind})
        recompute_scope(subject.ticket)

    return subjects
