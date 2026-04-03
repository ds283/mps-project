"""Add period_attachment_roles table

Revision ID: a3b5c1d9e7f2
Revises: 1a7bb7d0fb83
Create Date: 2026-04-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3b5c1d9e7f2'
down_revision = '1a7bb7d0fb83'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'period_attachment_roles',
        sa.Column('attachment_id', sa.Integer(), sa.ForeignKey('period_attachments.id'), nullable=False),
        sa.Column('role', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('attachment_id', 'role'),
    )


def downgrade():
    op.drop_table('period_attachment_roles')
