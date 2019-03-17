"""Add ProjectClass availability flag

Revision ID: d3bf7ff237de
Revises: fb1c84380a2f
Create Date: 2019-03-16 22:34:28.811336

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3bf7ff237de'
down_revision = 'fb1c84380a2f'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('project_classes', sa.Column('include_available', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('project_classes', 'include_available')
    # ### end Alembic commands ###
