"""Move popularity data to new PopularityRecord table

Revision ID: 44fbe504abdb
Revises: 6ec8e6ff2226
Create Date: 2018-07-13 14:53:03.394634

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '44fbe504abdb'
down_revision = '6ec8e6ff2226'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('popularity_record',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('liveproject_id', sa.Integer(), nullable=True),
    sa.Column('config_id', sa.Integer(), nullable=True),
    sa.Column('datestamp', sa.DateTime(), nullable=True),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('rank', sa.Integer(), nullable=True),
    sa.Column('total_number', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['config_id'], ['project_class_config.id'], ),
    sa.ForeignKeyConstraint(['liveproject_id'], ['live_projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_popularity_record_datestamp'), 'popularity_record', ['datestamp'], unique=False)
    op.drop_column('live_projects', 'popularity_percentile')
    op.drop_column('live_projects', 'popularity_index')
    op.drop_column('live_projects', 'popularity_rank')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('live_projects', sa.Column('popularity_rank', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True))
    op.add_column('live_projects', sa.Column('popularity_index', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True))
    op.add_column('live_projects', sa.Column('popularity_percentile', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True))
    op.drop_index(op.f('ix_popularity_record_datestamp'), table_name='popularity_record')
    op.drop_table('popularity_record')
    # ### end Alembic commands ###
