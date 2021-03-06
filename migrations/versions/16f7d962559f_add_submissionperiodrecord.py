"""Add SubmissionPeriodRecord

Revision ID: 16f7d962559f
Revises: e664f5131eb2
Create Date: 2018-09-07 01:18:55.093665

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '16f7d962559f'
down_revision = 'e664f5131eb2'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('submission_periods',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('config_id', sa.Integer(), nullable=True),
    sa.Column('submission_period', sa.Integer(), nullable=True),
    sa.Column('feedback_open', sa.Boolean(), nullable=True),
    sa.Column('feedback_id', sa.Integer(), nullable=True),
    sa.Column('feedback_timestamp', sa.DateTime(), nullable=True),
    sa.Column('feedback_deadline', sa.DateTime(), nullable=True),
    sa.Column('closed', sa.Boolean(), nullable=True),
    sa.Column('closed_id', sa.Integer(), nullable=True),
    sa.Column('closed_timestamp', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['closed_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['config_id'], ['project_class_config.id'], ),
    sa.ForeignKeyConstraint(['feedback_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.drop_column('project_class_config', 'feedback_open')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('project_class_config', sa.Column('feedback_open', mysql.TINYINT(display_width=1), autoincrement=False, nullable=True))
    op.drop_table('submission_periods')
    # ### end Alembic commands ###
