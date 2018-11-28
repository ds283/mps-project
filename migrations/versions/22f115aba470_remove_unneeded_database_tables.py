"""Remove unneeded database tables

Revision ID: 22f115aba470
Revises: 34ec3df416a2
Create Date: 2018-11-28 16:20:44.644503

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '22f115aba470'
down_revision = '34ec3df416a2'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('faculty_availability')
    op.drop_table('assessment_to_submitters')
    op.drop_table('submitter_availability')
    op.drop_table('submitter_not_attend')
    op.drop_table('assessment_to_assessors')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('assessment_to_assessors',
    sa.Column('assessment_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.Column('faculty_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['assessment_id'], ['presentation_assessments.id'], name='assessment_to_assessors_ibfk_1'),
    sa.ForeignKeyConstraint(['faculty_id'], ['faculty_data.id'], name='assessment_to_assessors_ibfk_2'),
    sa.PrimaryKeyConstraint('assessment_id', 'faculty_id'),
    mysql_default_charset='latin1',
    mysql_engine='InnoDB'
    )
    op.create_table('submitter_not_attend',
    sa.Column('assessment_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.Column('submitter_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['assessment_id'], ['presentation_assessments.id'], name='submitter_not_attend_ibfk_1'),
    sa.ForeignKeyConstraint(['submitter_id'], ['submission_records.id'], name='submitter_not_attend_ibfk_2'),
    sa.PrimaryKeyConstraint('assessment_id', 'submitter_id'),
    mysql_default_charset='latin1',
    mysql_engine='InnoDB'
    )
    op.create_table('submitter_availability',
    sa.Column('session_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.Column('submitter_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['presentation_sessions.id'], name='submitter_availability_ibfk_1'),
    sa.ForeignKeyConstraint(['submitter_id'], ['submission_records.id'], name='submitter_availability_ibfk_2'),
    sa.PrimaryKeyConstraint('session_id', 'submitter_id'),
    mysql_default_charset='latin1',
    mysql_engine='InnoDB'
    )
    op.create_table('assessment_to_submitters',
    sa.Column('assessment_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.Column('submitter_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['assessment_id'], ['presentation_assessments.id'], name='assessment_to_submitters_ibfk_1'),
    sa.ForeignKeyConstraint(['submitter_id'], ['submission_records.id'], name='assessment_to_submitters_ibfk_2'),
    sa.PrimaryKeyConstraint('assessment_id', 'submitter_id'),
    mysql_default_charset='latin1',
    mysql_engine='InnoDB'
    )
    op.create_table('faculty_availability',
    sa.Column('session_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.Column('faculty_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['faculty_id'], ['faculty_data.id'], name='faculty_availability_ibfk_1'),
    sa.ForeignKeyConstraint(['session_id'], ['presentation_sessions.id'], name='faculty_availability_ibfk_2'),
    sa.PrimaryKeyConstraint('session_id', 'faculty_id'),
    mysql_default_charset='latin1',
    mysql_engine='InnoDB'
    )
    # ### end Alembic commands ###
