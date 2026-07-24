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
State-transition actions for the ticket service layer: status changes, (un)assignment, comments,
logged email, and label add/remove. Each records the appropriate TicketEvent and keeps derived
state (subscriptions on assignment) consistent. None of these commit — the caller owns the
transaction.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from ...database import db
from ...models import TicketComment, TicketEmail, TicketEvent, TicketSubscription
from .events import record_event
from .subscriptions import subscribe


def change_status(ticket, new_status: int, actor=None) -> None:
    old = ticket.status
    if old == new_status:
        return
    ticket.status = new_status
    record_event(ticket, actor, TicketEvent.STATUS_CHANGED, {"from": old, "to": new_status})


def assign(ticket, user, actor=None, auto: bool = False) -> None:
    """Assign a ticket to a user (auto-subscribing them). Passing user=None unassigns."""
    if user is None:
        unassign(ticket, actor=actor)
        return

    old = ticket.assignee_id
    if old == user.id:
        return

    ticket.assignee_id = user.id
    payload = {"from": old, "to": user.id}
    if auto:
        payload["auto"] = True
    record_event(ticket, actor, TicketEvent.ASSIGNED, payload)
    subscribe(ticket, user, reason=TicketSubscription.ASSIGNEE, actor=actor)


def unassign(ticket, actor=None) -> None:
    old = ticket.assignee_id
    if old is None:
        return
    ticket.assignee_id = None
    record_event(ticket, actor, TicketEvent.UNASSIGNED, {"from": old})


def add_comment(ticket, author, body: str, actor=None) -> TicketComment:
    comment = TicketComment(
        ticket=ticket,
        author_id=(author.id if author is not None else None),
        body=body,
        created_at=datetime.now(),
    )
    db.session.add(comment)
    record_event(ticket, actor if actor is not None else author, TicketEvent.COMMENT_ADDED, {"preview": (body or "")[:80]})
    return comment


def log_email(
    ticket,
    *,
    direction: int,
    subject: str,
    body: Optional[str] = None,
    from_addr: Optional[str] = None,
    to_addrs=None,
    message_id: Optional[str] = None,
    logged_by=None,
    actor=None,
) -> TicketEmail:
    """Record a logged (outbound or manual) email against a ticket."""
    to_value = json.dumps(list(to_addrs)) if isinstance(to_addrs, (list, tuple)) else to_addrs

    email = TicketEmail(
        ticket=ticket,
        direction=direction,
        subject=subject,
        body=body,
        from_addr=from_addr,
        to_addrs=to_value,
        message_id=message_id,
        logged_by_id=(logged_by.id if logged_by is not None else None),
        logged_at=datetime.now(),
    )
    db.session.add(email)
    record_event(ticket, actor if actor is not None else logged_by, TicketEvent.EMAIL_LOGGED, {"subject": subject})
    return email


def rename_ticket(ticket, new_title: str, actor=None) -> None:
    old = ticket.title
    if old == new_title:
        return
    ticket.title = new_title
    record_event(ticket, actor, TicketEvent.TITLE_CHANGED, {"from": old, "to": new_title})


def add_label(ticket, label, actor=None) -> None:
    if ticket.labels.filter_by(id=label.id).first() is not None:
        return
    ticket.labels.append(label)
    record_event(ticket, actor, TicketEvent.LABEL_ADDED, {"label": label.id, "name": label.name})


def remove_label(ticket, label, actor=None) -> None:
    if ticket.labels.filter_by(id=label.id).first() is None:
        return
    ticket.labels.remove(label)
    record_event(ticket, actor, TicketEvent.LABEL_REMOVED, {"label": label.id, "name": label.name})
