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
Auto-assignment (routing) for the ticket service layer.

Rule (from the data-model spec §4):
  - |scope| == 1  -> auto-assign that class's convenor (recorded with an "auto" marker);
  - |scope| >  1  -> leave unassigned; it surfaces on every in-scope convenor's triage board;
  - |scope| == 0  -> not routed (General ticket).

apply_auto_assign only acts when the ticket is currently unassigned, so adding a subject that pushes
a ticket to multi-class never steals an existing owner (spec decision 3). It does not commit.
"""

from __future__ import annotations

from ...models import TicketEvent
from .events import record_event
from .scope import compute_scope_classes, primary_convenor_user


def apply_auto_assign(ticket, actor=None):
    """Apply the |scope| routing rule. Returns the assigned User, or None if left unassigned."""
    if ticket.assignee_id is not None:
        return ticket.assignee

    classes = compute_scope_classes(ticket)
    if len(classes) != 1:
        return None

    pclass = next(iter(classes))
    user = primary_convenor_user(pclass)
    if user is None:
        return None

    ticket.assignee_id = user.id
    record_event(ticket, actor, TicketEvent.ASSIGNED, {"from": None, "to": user.id, "auto": True})
    return user
