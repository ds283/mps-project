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
Subscriber (watcher) helpers for the ticket service layer. Subscriptions drive the "Watching" view
and the email fan-out. Auto-added subscribers: the opener, the assignee, and (on routing) the
in-scope convenor(s). None of these functions commit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ...database import db
from ...models import TicketEvent, TicketSubscription
from .events import record_event
from .scope import convenors_in_scope


def is_subscribed(user, ticket) -> bool:
    if user is None:
        return False
    return ticket.subscriptions.filter_by(user_id=user.id).first() is not None


def subscribe(ticket, user, reason: int = TicketSubscription.MANUAL, actor=None) -> Optional[TicketSubscription]:
    """
    Subscribe a user to a ticket. Idempotent: if the user is already subscribed, the existing
    subscription (and its original reason) is preserved and returned.
    """
    if user is None:
        return None

    existing = ticket.subscriptions.filter_by(user_id=user.id).first()
    if existing is not None:
        return existing

    subscription = TicketSubscription(ticket=ticket, user_id=user.id, reason=reason, created_at=datetime.now())
    db.session.add(subscription)
    record_event(ticket, actor if actor is not None else user, TicketEvent.SUBSCRIBED, {"user": user.id, "reason": reason})
    return subscription


def unsubscribe(ticket, user, actor=None) -> None:
    if user is None:
        return

    subscription = ticket.subscriptions.filter_by(user_id=user.id).first()
    if subscription is None:
        return

    db.session.delete(subscription)
    record_event(ticket, actor if actor is not None else user, TicketEvent.UNSUBSCRIBED, {"user": user.id})


def sync_convenor_subscriptions(ticket, actor=None) -> None:
    """Ensure every in-scope convenor is subscribed (reason = convenor). Idempotent."""
    for user in convenors_in_scope(ticket):
        subscribe(ticket, user, reason=TicketSubscription.CONVENOR, actor=actor)
