#
# Created by David Seery on 22/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""add TicketReadState and TicketInboxVisit

Revision ID: a1c4e7f0b3d6
Revises: f3b6d9a2c5e8
Create Date: 2026-07-22

Adds ticket_read_states (per-user, per-ticket "last read" marker) and ticket_inbox_visits
(per-user "last visited the personal inbox" marker), backing the faculty/office inbox reconciliation
against reference screen 2c (Unread rail view, unread dots, Activity feed, "since last visit" tiles).
"""

import sqlalchemy as sa
from alembic import op

revision = "a1c4e7f0b3d6"
down_revision = "f3b6d9a2c5e8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ticket_read_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("last_read_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticket_id", "user_id", name="uq_ticket_read_state_user"),
    )
    op.create_index(op.f("ix_ticket_read_states_ticket_id"), "ticket_read_states", ["ticket_id"], unique=False)
    op.create_index(op.f("ix_ticket_read_states_user_id"), "ticket_read_states", ["user_id"], unique=False)

    op.create_table(
        "ticket_inbox_visits",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("last_visited_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade():
    op.drop_table("ticket_inbox_visits")
    op.drop_index(op.f("ix_ticket_read_states_user_id"), table_name="ticket_read_states")
    op.drop_index(op.f("ix_ticket_read_states_ticket_id"), table_name="ticket_read_states")
    op.drop_table("ticket_read_states")
