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
Permission predicates for the ticket service layer, mirroring the data-model spec §8 matrix. They
read the ticket's cached scope (Ticket.scope_classes) rather than recomputing, so they stay
index-friendly. All take the acting User explicitly (no request context).
"""

from __future__ import annotations

from .subscriptions import is_subscribed


def is_admin_or_root(user) -> bool:
    return user is not None and (user.has_role("admin") or user.has_role("root"))


def _faculty_id(user):
    faculty = getattr(user, "faculty_data", None)
    return faculty.id if faculty is not None else None


def is_convenor_in_scope(user, ticket) -> bool:
    """True if `user` is convenor or co-convenor of any class in the ticket's (cached) scope."""
    if user is None:
        return False

    fid = _faculty_id(user)
    if fid is None:
        return False

    # ProjectClass.is_convenor expects a FacultyData id
    return any(pclass.is_convenor(fid) for pclass in ticket.scope_classes)


def is_assignee(user, ticket) -> bool:
    return user is not None and ticket.assignee_id == user.id


def can_view(user, ticket) -> bool:
    if is_admin_or_root(user) or is_convenor_in_scope(user, ticket) or is_assignee(user, ticket):
        return True
    if is_subscribed(user, ticket):
        return True
    return user is not None and ticket.creator_id == user.id


def can_comment(user, ticket) -> bool:
    if is_admin_or_root(user) or is_convenor_in_scope(user, ticket) or is_assignee(user, ticket):
        return True
    # faculty / office may comment if they are a participant / subscriber on the ticket
    return is_subscribed(user, ticket)


def can_change_status(user, ticket) -> bool:
    return is_admin_or_root(user) or is_convenor_in_scope(user, ticket) or is_assignee(user, ticket)


def can_assign(user, ticket) -> bool:
    return is_admin_or_root(user) or is_convenor_in_scope(user, ticket)


def can_label(user, ticket) -> bool:
    return is_admin_or_root(user) or is_convenor_in_scope(user, ticket) or is_assignee(user, ticket)


def can_manage_subscribers(user, ticket) -> bool:
    return is_admin_or_root(user) or is_convenor_in_scope(user, ticket) or is_assignee(user, ticket)


def can_edit_scope(user, ticket) -> bool:
    """Add/remove scope subjects: admin/root, a convenor of any in-scope class, or an office user
    in the ticket's tenant (a General ticket with no tenant is open to any office user)."""
    if is_admin_or_root(user) or is_convenor_in_scope(user, ticket):
        return True
    if user is not None and user.has_role("office"):
        if ticket.tenant_id is None:
            return True
        return user.tenants.filter_by(id=ticket.tenant_id).first() is not None
    return False


def can_manage_labels(user) -> bool:
    """Manage tenant label definitions: convenor (any class), or admin/root."""
    if is_admin_or_root(user):
        return True
    faculty = getattr(user, "faculty_data", None)
    return faculty is not None and faculty.is_convenor
