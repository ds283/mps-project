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
Admin/root visibility for the ticket assign and subscriber pickers.

A ticket that carries no tenant (a "General" ticket with no subjects, or a scope that otherwise
resolves to no tenant) has no convenor, no office pool, and no supervisor to fall back on — it can
still legitimately need an owner. `root` users are treated as global superusers and are always
offered, independent of tenant; `admin` users are tenant-scoped staff and are only offered once the
ticket has resolved to a definite tenant, and only if they are a member of that tenant (mirroring
the tenant-membership check already used for the "Office" picker section in app/tickets/detail.py).
"""

from __future__ import annotations

from ...models import Role, Tenant, User


def admin_root_users_for(ticket) -> list[dict]:
    """Candidate rows for the "Administrators" picker section: every `root` user (always), plus
    every `admin` user who is a member of the ticket's tenant (only once the ticket has a tenant).
    Deduplicated by user id — a user holding both roles is listed once, noted "Root"."""
    rows = {}

    for user in User.query.filter(User.roles.any(Role.name == "root")).order_by(User.last_name.asc()).all():
        rows[user.id] = {"user": user, "note": "Root"}

    if ticket.tenant_id is not None:
        admins = User.query.filter(User.roles.any(Role.name == "admin"), User.tenants.any(Tenant.id == ticket.tenant_id)).order_by(
            User.last_name.asc()
        )
        for user in admins.all():
            rows.setdefault(user.id, {"user": user, "note": "Admin"})

    return list(rows.values())
