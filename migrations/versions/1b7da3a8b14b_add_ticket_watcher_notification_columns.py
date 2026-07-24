#
# Created by David Seery on 24/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""add ticket watcher-notification columns

Revision ID: 1b7da3a8b14b
Revises: c3d9e2f6a1b4
Create Date: 2026-07-24

Adds the authorship/fan-out-tracking columns needed for the watcher-added-notification email
(app/tasks/ticket_notifications.py check_watcher_notifications). The deferred-dispatch debounce
itself is persisted as a DatabaseSchedulerEntry/CrontabSchedule row (see
app/shared/tickets/subscriptions.py._schedule_watcher_notification_check), not a Ticket column —
those tables already exist (see the celery_sqlalchemy_scheduler migrations).

- ticket_subscriptions.added_by_id: who performed the add (NULL for self-subscribe / automatic
  reasons).
- ticket_subscriptions.notify_pending: True while this subscription still needs its "you were
  added as a watcher" email.
"""

import sqlalchemy as sa
from alembic import op

revision = "1b7da3a8b14b"
down_revision = "c3d9e2f6a1b4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ticket_subscriptions", sa.Column("added_by_id", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_ticket_subscriptions_added_by_id"),
        "ticket_subscriptions",
        ["added_by_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_ticket_subscriptions_added_by_id_users"),
        "ticket_subscriptions",
        "users",
        ["added_by_id"],
        ["id"],
    )

    op.add_column(
        "ticket_subscriptions",
        sa.Column("notify_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("ticket_subscriptions", "notify_pending", server_default=None)


def downgrade():
    op.drop_column("ticket_subscriptions", "notify_pending")

    op.drop_constraint(op.f("fk_ticket_subscriptions_added_by_id_users"), "ticket_subscriptions", type_="foreignkey")
    op.drop_index(op.f("ix_ticket_subscriptions_added_by_id"), table_name="ticket_subscriptions")
    op.drop_column("ticket_subscriptions", "added_by_id")
