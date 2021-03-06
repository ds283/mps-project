"""Add ScheduleAttempt model

Revision ID: cd667ac74a34
Revises: ee2ef945e379
Create Date: 2018-10-07 01:58:17.315235

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cd667ac74a34'
down_revision = 'ee2ef945e379'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('scheduling_attempts',
    sa.Column('outcome', sa.Integer(), nullable=True),
    sa.Column('solver', sa.Integer(), nullable=True),
    sa.Column('construct_time', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('compute_time', sa.Numeric(precision=8, scale=3), nullable=True),
    sa.Column('score', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=255, collation='utf8_bin'), nullable=True),
    sa.Column('published', sa.Boolean(), nullable=True),
    sa.Column('celery_id', sa.String(length=255, collation='utf8_bin'), nullable=True),
    sa.Column('finished', sa.Boolean(), nullable=True),
    sa.Column('number_assessors', sa.Integer(), nullable=True),
    sa.Column('max_group_size', sa.Integer(), nullable=True),
    sa.Column('creator_id', sa.Integer(), nullable=True),
    sa.Column('creation_timestamp', sa.DateTime(), nullable=True),
    sa.Column('last_edit_id', sa.Integer(), nullable=True),
    sa.Column('last_edit_timestamp', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['creator_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['last_edit_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['presentation_assessments.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('scheduling_attempts')
    # ### end Alembic commands ###
