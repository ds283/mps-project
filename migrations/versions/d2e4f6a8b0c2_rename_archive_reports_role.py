#
# Created by David Seery on 19/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Rename role archive_reports to data_dashboard_reports

Revision ID: d2e4f6a8b0c2
Revises: b7c8d9e0f1a2
Create Date: 2026-06-19

Data-only migration.  Renames the existing "archive_reports" Role row to
"data_dashboard_reports" in place, matching the data_dashboard_AI /
data_dashboard_marking / data_dashboard_similarity naming convention.
Because both Flask-Security role membership (roles_users) and asset
access-control-list role grants key on Role.id rather than Role.name,
renaming the row in place carries every existing holder and every
existing asset ACL grant across automatically — no join-table changes
are needed. A no-op on any install that never had an "archive_reports"
role (e.g. a fresh database); ensure_roles() creates "data_dashboard_reports"
on next startup in that case.
"""

from alembic import op
import sqlalchemy as sa

revision = "d2e4f6a8b0c2"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None

_OLD_NAME = "archive_reports"
_NEW_NAME = "data_dashboard_reports"
_NEW_DESCRIPTION = (
    "Read-only access to the AVD dashboard for all project classes and cycles "
    "belonging to the user's tenants. Does not grant convenor or marking "
    "permissions."
)
_NEW_COLOUR = "#1a8a8a"


def upgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE roles SET name = :new_name, description = :description, colour = :colour WHERE name = :old_name"),
        {
            "new_name": _NEW_NAME,
            "description": _NEW_DESCRIPTION,
            "colour": _NEW_COLOUR,
            "old_name": _OLD_NAME,
        },
    )


def downgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE roles SET name = :old_name WHERE name = :new_name"),
        {"old_name": _OLD_NAME, "new_name": _NEW_NAME},
    )
