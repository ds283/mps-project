"""Widen language_analysis column to MEDIUMTEXT

Revision ID: a1b2c3d4e5f6
Revises: 34e6f9e9f809
Create Date: 2026-04-09 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '34e6f9e9f809'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE submission_records MODIFY COLUMN language_analysis MEDIUMTEXT"
    )


def downgrade():
    op.execute(
        "ALTER TABLE submission_records MODIFY COLUMN language_analysis TEXT"
    )
