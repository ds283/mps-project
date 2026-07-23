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
Derived class-scope engine for the ticket service layer.

A ticket is not owned by a single ProjectClass column; its class scope is *derived* from its
subjects and cached in the ticket_class_scope association table (Ticket.scope_classes). This module
computes that scope, keeps the cache in sync, and resolves the convenor(s) responsible for a
ticket's scope.
"""

from __future__ import annotations

from typing import List, Optional, Set

from ...database import db
from ...models import TicketSubject, TicketSubjectTombstone


def home_class(student):
    """
    The ProjectClass a student "sits in".

    Works for both SelectingStudent and SubmittingStudent, since both expose
    `.config.project_class`. Returns None if the student or its config is missing.
    """
    if student is None:
        return None

    config = getattr(student, "config", None)
    if config is None:
        return None

    return getattr(config, "project_class", None)


def compute_scope_classes(ticket) -> Set:
    """
    Compute the set of ProjectClass a ticket touches, from its subjects:
      - a pinned project_class subject contributes that class directly;
      - a student subject contributes the student's home_class.
    A ticket with no subjects (a "General" ticket) has empty scope. A tombstoned subject (its
    linked student has been deleted) contributes nothing, the same as a missing project class.
    """
    classes = set()

    for subject in ticket.subjects:
        target = subject.target
        if target is None or isinstance(target, TicketSubjectTombstone):
            continue

        if subject.kind == TicketSubject.PROJECT_CLASS:
            classes.add(target)
        else:
            hc = home_class(target)
            if hc is not None:
                classes.add(hc)

    return classes


def derive_tenant_id(classes) -> Optional[int]:
    """
    Derive the cached tenant for a ticket from its scope classes. Single-tenant scope is the norm;
    for the (unusual) multi-tenant case we pick the lowest tenant id deterministically. Empty scope
    (General ticket) yields None.
    """
    ids = sorted({c.tenant_id for c in classes if c.tenant_id is not None})
    if not ids:
        return None
    return ids[0]


def recompute_scope(ticket) -> Set:
    """
    Rebuild a ticket's cached scope (Ticket.scope_classes) from its subjects, and refresh the cached
    tenant_id. Flushes first so pending subject rows are visible. Does not commit.
    """
    db.session.flush()

    classes = compute_scope_classes(ticket)
    current = set(ticket.scope_classes.all())

    for pclass in classes - current:
        ticket.scope_classes.append(pclass)
    for pclass in current - classes:
        ticket.scope_classes.remove(pclass)

    ticket.tenant_id = derive_tenant_id(classes)
    return classes


def primary_convenor_user(pclass):
    """The User of a class's principal convenor (not co-convenors), or None."""
    if pclass is None or pclass.convenor is None:
        return None
    return pclass.convenor.user


def class_convenor_users(pclass) -> List:
    """All convenor Users of a class: principal convenor + co-convenors."""
    users = []

    if pclass.convenor is not None and pclass.convenor.user is not None:
        users.append(pclass.convenor.user)

    for coconvenor in pclass.coconvenors:
        if coconvenor.user is not None:
            users.append(coconvenor.user)

    return users


def convenors_in_scope(ticket) -> List:
    """De-duplicated list of every convenor User across a ticket's scope classes."""
    seen = {}
    for pclass in compute_scope_classes(ticket):
        for user in class_convenor_users(pclass):
            seen[user.id] = user
    return list(seen.values())
