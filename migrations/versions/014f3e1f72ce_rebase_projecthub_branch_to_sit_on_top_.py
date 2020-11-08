"""Rebase projecthub branch to sit on top of changes in master to allow 2nd marker/presentation UI elements disabled

Revision ID: 014f3e1f72ce
Revises: b5b776c5e78e, 428eea9fbcc6
Create Date: 2020-11-08 21:51:37.858368

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '014f3e1f72ce'
down_revision = ('b5b776c5e78e', '428eea9fbcc6')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
