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
Low-level TicketEvent helpers for the ticket service layer.

These functions mutate the SQLAlchemy session (add rows, set attributes) but never commit — the
caller (a view, or a Celery task) owns the transaction and is responsible for committing, typically
via log_db_commit(). They also take no dependency on Flask request context: the acting user is
always passed in explicitly as `actor`, so the same helpers work from a background task.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from ...database import db
from ...models import TicketEvent


def touch(ticket, actor=None) -> None:
    """
    Record activity on a ticket: bump last_edit_timestamp (and last_edit_id, when an actor is
    known). last_edit_timestamp is the canonical "recently updated" field — there is no separate
    updated_at column.
    """
    ticket.last_edit_timestamp = datetime.now()
    if actor is not None:
        ticket.last_edit_id = actor.id


def record_event(ticket, actor, kind: int, payload: Optional[dict] = None, *, bump_updated: bool = True) -> TicketEvent:
    """
    Append an audit event to a ticket.

    :param ticket: the Ticket
    :param actor: the acting User (may be None for system actions)
    :param kind: a TicketEventKindMixin constant
    :param payload: optional JSON-serialisable before/after detail
    :param bump_updated: whether to also bump the ticket's last_edit_timestamp / last_edit_id
    """
    event = TicketEvent(
        ticket=ticket,
        actor_id=(actor.id if actor is not None else None),
        kind=kind,
        payload_json=(json.dumps(payload) if payload is not None else None),
        created_at=datetime.now(),
    )
    db.session.add(event)

    if bump_updated:
        touch(ticket, actor)

    return event
