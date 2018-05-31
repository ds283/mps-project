"""Merge models from celery_sqlalchemy_scheduler

Revision ID: 57b72f76d9de
Revises: 357c38215443
Create Date: 2018-05-31 13:11:19.226796

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '57b72f76d9de'
down_revision = '357c38215443'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('celery_crontabs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('minute', sa.String(length=64), nullable=True),
    sa.Column('hour', sa.String(length=64), nullable=True),
    sa.Column('day_of_week', sa.String(length=64), nullable=True),
    sa.Column('day_of_month', sa.String(length=64), nullable=True),
    sa.Column('month_of_year', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('celery_intervals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('every', sa.Integer(), nullable=False),
    sa.Column('period', sa.String(length=24), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('celery_schedules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('task', sa.String(length=255), nullable=True),
    sa.Column('interval_id', sa.Integer(), nullable=True),
    sa.Column('crontab_id', sa.Integer(), nullable=True),
    sa.Column('arguments', sa.String(length=255), nullable=True),
    sa.Column('keyword_arguments', sa.String(length=255), nullable=True),
    sa.Column('queue', sa.String(length=255), nullable=True),
    sa.Column('exchange', sa.String(length=255), nullable=True),
    sa.Column('routing_key', sa.String(length=255), nullable=True),
    sa.Column('expires', sa.DateTime(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=True),
    sa.Column('last_run_at', sa.DateTime(), nullable=True),
    sa.Column('total_run_count', sa.Integer(), nullable=True),
    sa.Column('date_changed', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['crontab_id'], ['celery_crontabs.id'], ),
    sa.ForeignKeyConstraint(['interval_id'], ['celery_intervals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('celery_schedules')
    op.drop_table('celery_intervals')
    op.drop_table('celery_crontabs')
    # ### end Alembic commands ###
