"""Add colour field to ProjectClass

Revision ID: 72e335a48996
Revises: 7a2480915ae2
Create Date: 2018-06-15 17:05:24.116181

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '72e335a48996'
down_revision = '7a2480915ae2'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('project_classes', sa.Column('colour', sa.String(length=255), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('project_classes', 'colour')
    # ### end Alembic commands ###
