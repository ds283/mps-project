"""Add circulation datestamps to MatchingAttempt

Revision ID: eb7294fbdbe1
Revises: 0e4154edab01
Create Date: 2019-06-11 11:35:19.579819

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'eb7294fbdbe1'
down_revision = '0e4154edab01'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('matching_attempts', sa.Column('draft_to_selectors', sa.DateTime(), nullable=True))
    op.add_column('matching_attempts', sa.Column('draft_to_supervisors', sa.DateTime(), nullable=True))
    op.add_column('matching_attempts', sa.Column('final_to_selectors', sa.DateTime(), nullable=True))
    op.add_column('matching_attempts', sa.Column('final_to_supervisors', sa.DateTime(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('matching_attempts', 'final_to_supervisors')
    op.drop_column('matching_attempts', 'final_to_selectors')
    op.drop_column('matching_attempts', 'draft_to_supervisors')
    op.drop_column('matching_attempts', 'draft_to_selectors')
    # ### end Alembic commands ###
