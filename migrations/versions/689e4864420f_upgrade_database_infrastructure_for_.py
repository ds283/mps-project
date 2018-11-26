"""Upgrade database infrastructure for availabilities

Revision ID: 689e4864420f
Revises: bfb79be8a4a1
Create Date: 2018-11-23 01:30:32.101140

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '689e4864420f'
down_revision = 'bfb79be8a4a1'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('assessment_to_submitters',
    sa.Column('assessment_id', sa.Integer(), nullable=False),
    sa.Column('submitter_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['assessment_id'], ['presentation_assessments.id'], ),
    sa.ForeignKeyConstraint(['submitter_id'], ['submission_records.id'], ),
    sa.PrimaryKeyConstraint('assessment_id', 'submitter_id')
    )
    op.create_table('submitter_not_attend',
    sa.Column('assessment_id', sa.Integer(), nullable=False),
    sa.Column('submitter_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['assessment_id'], ['presentation_assessments.id'], ),
    sa.ForeignKeyConstraint(['submitter_id'], ['submission_records.id'], ),
    sa.PrimaryKeyConstraint('assessment_id', 'submitter_id')
    )
    op.drop_table('assessment_not_attend')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('assessment_not_attend',
    sa.Column('assessment_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.Column('submitted_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['assessment_id'], ['presentation_assessments.id'], name='assessment_not_attend_ibfk_1'),
    sa.ForeignKeyConstraint(['submitted_id'], ['submission_records.id'], name='assessment_not_attend_ibfk_2'),
    sa.PrimaryKeyConstraint('assessment_id', 'submitted_id'),
    mysql_default_charset='latin1',
    mysql_engine='InnoDB'
    )
    op.drop_table('submitter_not_attend')
    op.drop_table('assessment_to_submitters')
    # ### end Alembic commands ###