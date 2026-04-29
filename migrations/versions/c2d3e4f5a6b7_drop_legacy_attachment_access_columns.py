#
# Created by David Seery on 29/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Drop legacy boolean access-control columns from period_attachments and submission_attachments

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-04-29

Removes publish_to_students, include_marker_emails, and include_supervisor_emails from both
period_attachments and submission_attachments.  These were retained after the migration to
role-based access control (PeriodAttachmentRole / SubmissionAttachmentRole) to allow data
migration, but are now fully unused.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("period_attachments", schema=None) as batch_op:
        batch_op.drop_column("publish_to_students")
        batch_op.drop_column("include_marker_emails")
        batch_op.drop_column("include_supervisor_emails")

    with op.batch_alter_table("submission_attachments", schema=None) as batch_op:
        batch_op.drop_column("publish_to_students")
        batch_op.drop_column("include_marker_emails")
        batch_op.drop_column("include_supervisor_emails")


def downgrade():
    with op.batch_alter_table("submission_attachments", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("include_supervisor_emails", sa.Boolean(), nullable=True, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("include_marker_emails", sa.Boolean(), nullable=True, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("publish_to_students", sa.Boolean(), nullable=True, server_default=sa.false())
        )

    with op.batch_alter_table("period_attachments", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("include_supervisor_emails", sa.Boolean(), nullable=True, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("include_marker_emails", sa.Boolean(), nullable=True, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("publish_to_students", sa.Boolean(), nullable=True, server_default=sa.false())
        )
