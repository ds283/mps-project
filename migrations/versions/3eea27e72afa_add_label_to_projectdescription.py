"""Add label to ProjectDescription

Revision ID: 3eea27e72afa
Revises: 16407912c83e
Create Date: 2018-08-27 22:02:47.142189

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3eea27e72afa'
down_revision = '16407912c83e'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('descriptions', sa.Column('label', sa.String(length=255), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('descriptions', 'label')
    # ### end Alembic commands ###
