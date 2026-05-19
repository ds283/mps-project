"""Remove legacy marking fields from submission_roles

Revision ID: a5b6c7d8e9f0
Revises: c1d2e3f4a5b6
Create Date: 2026-05-19

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a5b6c7d8e9f0"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("submission_roles", "grade")
    op.drop_column("submission_roles", "weight")
    op.drop_column("submission_roles", "justification")
    op.drop_column("submission_roles", "signed_off")


def downgrade():
    op.add_column("submission_roles", sa.Column("signed_off", sa.DateTime(), nullable=True))
    op.add_column("submission_roles", sa.Column("justification", sa.Text(collation="utf8_bin"), nullable=True))
    op.add_column("submission_roles", sa.Column("weight", sa.Numeric(precision=8, scale=3), nullable=True))
    op.add_column("submission_roles", sa.Column("grade", sa.Integer(), nullable=True))
