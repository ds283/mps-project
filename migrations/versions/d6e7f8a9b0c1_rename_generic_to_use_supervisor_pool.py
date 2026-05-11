"""Rename generic to use_supervisor_pool on projects and live_projects

Revision ID: d6e7f8a9b0c1
Revises: c4d5e6f7a8b9
Create Date: 2026-05-11

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d6e7f8a9b0c1"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column(
            "generic",
            new_column_name="use_supervisor_pool",
            existing_type=sa.Boolean(),
            existing_nullable=True,
        )
    with op.batch_alter_table("live_projects") as batch_op:
        batch_op.alter_column(
            "generic",
            new_column_name="use_supervisor_pool",
            existing_type=sa.Boolean(),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column(
            "use_supervisor_pool",
            new_column_name="generic",
            existing_type=sa.Boolean(),
            existing_nullable=True,
        )
    with op.batch_alter_table("live_projects") as batch_op:
        batch_op.alter_column(
            "use_supervisor_pool",
            new_column_name="generic",
            existing_type=sa.Boolean(),
            existing_nullable=True,
        )
