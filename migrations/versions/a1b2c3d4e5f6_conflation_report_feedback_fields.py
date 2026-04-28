#
# Created by David Seery on 28/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Add feedback generation tracking fields to conflation_reports

Revision ID: a1b2c3d4e5f6
Revises: f5b6c7d8e9a0
Create Date: 2026-04-28

Adds three columns to conflation_reports:
  - recipe: label of the FeedbackRecipe used to generate PDFs (archived string, not FK)
  - feedback_celery_id: Celery task ID for an in-progress PDF generation
  - feedback_generation_failed: True when the last PDF generation attempt failed
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f5b6c7d8e9a0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("conflation_reports", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("recipe", sa.String(255, collation="utf8_bin"), nullable=True)
        )
        batch_op.add_column(
            sa.Column("feedback_celery_id", sa.String(255, collation="utf8_bin"), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "feedback_generation_failed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    with op.batch_alter_table("conflation_reports", schema=None) as batch_op:
        batch_op.drop_column("feedback_generation_failed")
        batch_op.drop_column("feedback_celery_id")
        batch_op.drop_column("recipe")
