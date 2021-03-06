"""Add skip_matching override flag to ProjectClassConfig

Revision ID: bfb79be8a4a1
Revises: e5f72ab6999c
Create Date: 2018-11-22 09:37:27.772005

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bfb79be8a4a1'
down_revision = 'e5f72ab6999c'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('project_class_config', sa.Column('skip_matching', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('project_class_config', 'skip_matching')
    # ### end Alembic commands ###
