#
# Created by David Seery on 22/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""add tickets.source_task_id provenance column

Revision ID: d4a9c7e2b8f5
Revises: c2f5a8b3e6d1
Create Date: 2026-07-22

Adds a nullable, indexed provenance column recording the ConvenorTask id each ticket was migrated
from (used by the Phase 8 ORM data migration for idempotency and audit). Not a foreign key, since
the convenor_tasks tables are dropped at teardown.
"""

import sqlalchemy as sa
from alembic import op

revision = "d4a9c7e2b8f5"
down_revision = "c2f5a8b3e6d1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tickets", sa.Column("source_task_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_tickets_source_task_id"), "tickets", ["source_task_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_tickets_source_task_id"), table_name="tickets")
    op.drop_column("tickets", "source_task_id")
