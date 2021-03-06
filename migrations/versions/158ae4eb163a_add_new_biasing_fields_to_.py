"""Add new biasing fields to MatchingAttempt

Revision ID: 158ae4eb163a
Revises: d921b21218ef
Create Date: 2019-06-04 13:31:18.919962

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '158ae4eb163a'
down_revision = 'd921b21218ef'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('matching_attempts', sa.Column('CATS_violation_penalty', sa.Numeric(precision=8, scale=3), nullable=True))
    op.add_column('matching_attempts', sa.Column('marking_pressure', sa.Numeric(precision=8, scale=3), nullable=True))
    op.add_column('matching_attempts', sa.Column('no_assignment_penalty', sa.Numeric(precision=8, scale=3), nullable=True))
    op.add_column('matching_attempts', sa.Column('supervising_pressure', sa.Numeric(precision=8, scale=3), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('matching_attempts', 'supervising_pressure')
    op.drop_column('matching_attempts', 'no_assignment_penalty')
    op.drop_column('matching_attempts', 'marking_pressure')
    op.drop_column('matching_attempts', 'CATS_violation_penalty')
    # ### end Alembic commands ###
