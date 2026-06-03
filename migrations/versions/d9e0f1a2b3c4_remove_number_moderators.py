"""Remove number_moderators from SubmissionPeriodDefinition and SubmissionPeriodRecord

The moderator assignment system now works via MarkingWorkflow (convenor-driven,
post-submission). The number_moderators field was used by the old pre-assignment
system which is no longer in operation.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-06-02

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

# revision identifiers, used by Alembic.
revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa_inspect(op.get_bind())

    # Drop number_moderators from period_definitions (SubmissionPeriodDefinition.__tablename__)
    if "period_definitions" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("period_definitions")]
        if "number_moderators" in cols:
            with op.batch_alter_table("period_definitions") as batch_op:
                batch_op.drop_column("number_moderators")

    # Drop number_moderators from submission_periods (SubmissionPeriodRecord.__tablename__)
    if "submission_periods" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("submission_periods")]
        if "number_moderators" in cols:
            with op.batch_alter_table("submission_periods") as batch_op:
                batch_op.drop_column("number_moderators")


def downgrade():
    insp = sa_inspect(op.get_bind())

    if "period_definitions" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("period_definitions")]
        if "number_moderators" not in cols:
            with op.batch_alter_table("period_definitions") as batch_op:
                batch_op.add_column(sa.Column("number_moderators", sa.Integer(), nullable=True))

    if "submission_periods" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("submission_periods")]
        if "number_moderators" not in cols:
            with op.batch_alter_table("submission_periods") as batch_op:
                batch_op.add_column(sa.Column("number_moderators", sa.Integer(), nullable=True))
