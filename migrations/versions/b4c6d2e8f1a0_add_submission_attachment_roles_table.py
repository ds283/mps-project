"""Add submission_attachment_roles table

Revision ID: b4c6d2e8f1a0
Revises: a3b5c1d9e7f2
Create Date: 2026-04-03 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4c6d2e8f1a0'
down_revision = 'a3b5c1d9e7f2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'submission_attachment_roles',
        sa.Column('attachment_id', sa.Integer(),
                  sa.ForeignKey('submission_attachments.id'), nullable=False),
        sa.Column('role', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('attachment_id', 'role'),
    )


def downgrade():
    op.drop_table('submission_attachment_roles')
