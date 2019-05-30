"""Add key2 fields to MatchingEnumeration

Revision ID: 1df13a7d6ec0
Revises: d30791be2859
Create Date: 2019-05-09 16:47:07.304292

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1df13a7d6ec0'
down_revision = 'd30791be2859'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('matching_enumerations', sa.Column('key2', sa.Integer(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('matching_enumerations', 'key2')
    # ### end Alembic commands ###