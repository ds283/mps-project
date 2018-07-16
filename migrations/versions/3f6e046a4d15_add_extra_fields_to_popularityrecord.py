"""Add extra fields to PopularityRecord

Revision ID: 3f6e046a4d15
Revises: 44fbe504abdb
Create Date: 2018-07-13 19:35:56.553666

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '3f6e046a4d15'
down_revision = '44fbe504abdb'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('popularity_record', sa.Column('bookmarks', sa.Integer(), nullable=True))
    op.add_column('popularity_record', sa.Column('bookmarks_rank', sa.Integer(), nullable=True))
    op.add_column('popularity_record', sa.Column('score_rank', sa.Integer(), nullable=True))
    op.add_column('popularity_record', sa.Column('selections', sa.Integer(), nullable=True))
    op.add_column('popularity_record', sa.Column('selections_rank', sa.Integer(), nullable=True))
    op.add_column('popularity_record', sa.Column('views', sa.Integer(), nullable=True))
    op.add_column('popularity_record', sa.Column('views_rank', sa.Integer(), nullable=True))
    op.drop_column('popularity_record', 'rank')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('popularity_record', sa.Column('rank', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True))
    op.drop_column('popularity_record', 'views_rank')
    op.drop_column('popularity_record', 'views')
    op.drop_column('popularity_record', 'selections_rank')
    op.drop_column('popularity_record', 'selections')
    op.drop_column('popularity_record', 'score_rank')
    op.drop_column('popularity_record', 'bookmarks_rank')
    op.drop_column('popularity_record', 'bookmarks')
    # ### end Alembic commands ###
