"""Add matching flag to ProjectClass

Revision ID: f5fc7e51cce2
Revises: 9717caa9b694
Create Date: 2018-08-09 16:31:26.618611

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f5fc7e51cce2'
down_revision = '9717caa9b694'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('project_classes', sa.Column('do_matching', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('project_classes', 'do_matching')
    # ### end Alembic commands ###
