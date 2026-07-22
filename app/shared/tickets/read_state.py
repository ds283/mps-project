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
Per-user read/visit tracking for the personal ticket inbox (design screen 2c): the Unread rail
view, unread dots, the Activity feed, and the "since you last visited" metric tiles. None of these
functions commit — the caller owns the transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ...database import db
from ...models import Ticket, TicketInboxVisit, TicketReadState


def mark_read(ticket: Ticket, user) -> None:
    """Upsert the caller's read marker for `ticket` to now."""
    if user is None:
        return

    state = TicketReadState.query.filter_by(ticket_id=ticket.id, user_id=user.id).first()
    now = datetime.now()
    if state is None:
        db.session.add(TicketReadState(ticket_id=ticket.id, user_id=user.id, last_read_at=now))
    else:
        state.last_read_at = now


def is_unread(ticket: Ticket, user) -> bool:
    """
    A ticket is unread for `user` if it has been edited since their last read marker (or they have
    never read it) — except for the ticket's own creator, for whom it is never "unread".
    """
    if user is None:
        return False
    if ticket.creator_id == user.id:
        return False
    if ticket.last_edit_timestamp is None:
        return False

    state = TicketReadState.query.filter_by(ticket_id=ticket.id, user_id=user.id).first()
    if state is None:
        return True
    return ticket.last_edit_timestamp > state.last_read_at


def record_inbox_visit(user) -> Optional[datetime]:
    """
    Upsert `user`'s personal-inbox last-visited marker to now, returning the *previous* value (or
    None on a first-ever visit) so the caller can use it as the "since last visit" cutoff for this
    render.
    """
    if user is None:
        return None

    visit = TicketInboxVisit.query.filter_by(user_id=user.id).first()
    previous = visit.last_visited_at if visit is not None else None
    now = datetime.now()
    if visit is None:
        db.session.add(TicketInboxVisit(user_id=user.id, last_visited_at=now))
    else:
        visit.last_visited_at = now
    return previous
