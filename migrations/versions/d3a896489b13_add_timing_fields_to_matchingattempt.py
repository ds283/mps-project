"""Add timing fields to MatchingAttempt

Revision ID: d3a896489b13
Revises: 421d8688e288
Create Date: 2018-08-22 11:47:51.478947

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3a896489b13'
down_revision = '421d8688e288'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('matching_attempts', sa.Column('compute_time', sa.Numeric(), nullable=True))
    op.add_column('matching_attempts', sa.Column('construct_time', sa.Numeric(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('matching_attempts', 'construct_time')
    op.drop_column('matching_attempts', 'compute_time')
    # ### end Alembic commands ###
