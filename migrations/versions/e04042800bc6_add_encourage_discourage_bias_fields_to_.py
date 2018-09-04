"""Add encourage/discourage bias fields to MatchingAttempt

Revision ID: e04042800bc6
Revises: c04b278ed92c
Create Date: 2018-08-31 14:58:21.094970

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e04042800bc6'
down_revision = 'c04b278ed92c'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('matching_attempts', sa.Column('bookmark_bias', sa.Numeric(precision=8, scale=3), nullable=True))
    op.add_column('matching_attempts', sa.Column('discourage_bias', sa.Numeric(precision=8, scale=3), nullable=True))
    op.add_column('matching_attempts', sa.Column('encourage_bias', sa.Numeric(precision=8, scale=3), nullable=True))
    op.add_column('matching_attempts', sa.Column('strong_discourage_bias', sa.Numeric(precision=8, scale=3), nullable=True))
    op.add_column('matching_attempts', sa.Column('strong_encourage_bias', sa.Numeric(precision=8, scale=3), nullable=True))
    op.add_column('matching_attempts', sa.Column('use_hints', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('matching_attempts', 'use_hints')
    op.drop_column('matching_attempts', 'strong_encourage_bias')
    op.drop_column('matching_attempts', 'strong_discourage_bias')
    op.drop_column('matching_attempts', 'encourage_bias')
    op.drop_column('matching_attempts', 'discourage_bias')
    op.drop_column('matching_attempts', 'bookmark_bias')
    # ### end Alembic commands ###
