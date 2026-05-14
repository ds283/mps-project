"""Add convenor_intervention flag to submitter_report

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-05-14

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c1d2e3f4a5b6"
down_revision = "b0c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "submitter_reports",
        sa.Column(
            "convenor_intervention",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade():
    op.drop_column("submitter_reports", "convenor_intervention")
