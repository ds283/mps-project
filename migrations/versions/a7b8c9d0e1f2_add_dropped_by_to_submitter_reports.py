#
# Created by David Seery on 03/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Add dropped_by tracking fields to submitter_reports

Revision ID: a7b8c9d0e1f2
Revises: a6b7c8d9e0f1
Create Date: 2026-06-03

Adds dropped_by_id (FK to users) and dropped_by_timestamp to submitter_reports
so that the convenor who withdraws a student and the time of withdrawal are recorded.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("submitter_reports", sa.Column("dropped_by_id", sa.Integer(), nullable=True))
    op.add_column("submitter_reports", sa.Column("dropped_by_timestamp", sa.DateTime(), nullable=True))
    op.create_foreign_key(
        "fk_submitter_reports_dropped_by_id",
        "submitter_reports",
        "users",
        ["dropped_by_id"],
        ["id"],
    )


def downgrade():
    op.drop_constraint("fk_submitter_reports_dropped_by_id", "submitter_reports", type_="foreignkey")
    op.drop_column("submitter_reports", "dropped_by_timestamp")
    op.drop_column("submitter_reports", "dropped_by_id")
