"""Merge rebased projechub branch migrations

Revision ID: a8cbbc5efcee
Revises: 014f3e1f72ce, 9dba4fb0de78
Create Date: 2021-06-10 15:36:41.976627

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a8cbbc5efcee'
down_revision = ('014f3e1f72ce', '9dba4fb0de78')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
