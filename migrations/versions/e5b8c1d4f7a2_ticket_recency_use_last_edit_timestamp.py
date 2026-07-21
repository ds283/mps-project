#
# Created by David Seery on 22/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""ticket recency: drop tickets.updated_at, use last_edit_timestamp

Revision ID: e5b8c1d4f7a2
Revises: a1c4e7b9d2f6
Create Date: 2026-07-22

Removes the redundant tickets.updated_at column (and its index): activity recency now uses the
EditingMetadataMixin last_edit_timestamp column, which the service layer bumps together with
last_edit_id on every event. Adds an index on last_edit_timestamp to keep the ledger's
"recently updated" sort efficient.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e5b8c1d4f7a2"
down_revision = "a1c4e7b9d2f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(op.f("ix_tickets_last_edit_timestamp"), "tickets", ["last_edit_timestamp"], unique=False)
    op.drop_index(op.f("ix_tickets_updated_at"), table_name="tickets")
    op.drop_column("tickets", "updated_at")


def downgrade():
    op.add_column("tickets", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_tickets_updated_at"), "tickets", ["updated_at"], unique=False)
    op.drop_index(op.f("ix_tickets_last_edit_timestamp"), table_name="tickets")
