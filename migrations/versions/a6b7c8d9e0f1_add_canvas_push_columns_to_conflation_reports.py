#
# Created by David Seery on 02/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Add Canvas push columns to conflation_reports

Revision ID: a6b7c8d9e0f1
Revises: e0f1a2b3c4d5
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa

revision = "a6b7c8d9e0f1"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("conflation_reports", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "canvas_grade_target",
                sa.String(length=255, collation="utf8_bin"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "canvas_grade_pushed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("canvas_grade_push_timestamp", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "canvas_feedback_pushed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("canvas_feedback_push_timestamp", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "canvas_file_ids",
                sa.Text(collation="utf8_bin"),
                nullable=True,
            )
        )


def downgrade():
    with op.batch_alter_table("conflation_reports", schema=None) as batch_op:
        batch_op.drop_column("canvas_file_ids")
        batch_op.drop_column("canvas_feedback_push_timestamp")
        batch_op.drop_column("canvas_feedback_pushed")
        batch_op.drop_column("canvas_grade_push_timestamp")
        batch_op.drop_column("canvas_grade_pushed")
        batch_op.drop_column("canvas_grade_target")
