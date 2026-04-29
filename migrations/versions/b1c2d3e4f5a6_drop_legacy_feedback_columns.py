#
# Created by David Seery on 28/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Drop legacy inline-feedback columns from submission_role and submission_record tables

Revision ID: b1c2d3e4f5a6
Revises: f0a1b2c3d4e5
Create Date: 2026-04-28

Removes the old per-role feedback fields (positive_feedback, improvements_feedback,
submitted_feedback, feedback_timestamp, acknowledge_student, response, submitted_response,
response_timestamp, feedback_sent, feedback_push_id, feedback_push_timestamp) from
submission_role.

Also removes the aggregated feedback tracking fields (feedback_generated, feedback_sent,
feedback_push_id, feedback_push_timestamp) from submission_record.

The secondary table submission_record_to_feedback_report is retained: it is now populated
when feedback PDFs are generated via the MarkingEvent workflow, providing the SubmissionRecord
with a direct link to its feedback reports (used by the document manager view).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b1c2d3e4f5a6"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    # Drop legacy feedback columns from submission_role
    with op.batch_alter_table("submission_roles", schema=None) as batch_op:
        batch_op.drop_column("positive_feedback")
        batch_op.drop_column("improvements_feedback")
        batch_op.drop_column("submitted_feedback")
        batch_op.drop_column("feedback_timestamp")
        batch_op.drop_column("acknowledge_student")
        batch_op.drop_column("response")
        batch_op.drop_column("submitted_response")
        batch_op.drop_column("response_timestamp")
        batch_op.drop_column("feedback_sent")
        batch_op.drop_column("feedback_push_id")
        batch_op.drop_column("feedback_push_timestamp")

    # Drop legacy feedback tracking columns from submission_record
    with op.batch_alter_table("submission_records", schema=None) as batch_op:
        batch_op.drop_column("feedback_generated")
        batch_op.drop_column("feedback_sent")
        batch_op.drop_column("feedback_push_id")
        batch_op.drop_column("feedback_push_timestamp")


def downgrade():
    # Restore submission_record legacy columns
    with op.batch_alter_table("submission_records", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("feedback_push_timestamp", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "feedback_push_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "feedback_sent",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "feedback_generated",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    # Restore submission_role legacy columns
    with op.batch_alter_table("submission_roles", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("feedback_push_timestamp", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "feedback_push_id",
                sa.Integer(),
                sa.ForeignKey("users.id"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "feedback_sent",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column("response_timestamp", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "submitted_response",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column("response", sa.Text(collation="utf8_bin"), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "acknowledge_student",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column("feedback_timestamp", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "submitted_feedback",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "improvements_feedback",
                sa.Text(collation="utf8_bin"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "positive_feedback",
                sa.Text(collation="utf8_bin"),
                nullable=True,
            )
        )

