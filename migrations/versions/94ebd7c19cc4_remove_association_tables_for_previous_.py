"""Remove association tables for previous approach to confirmations

Revision ID: 94ebd7c19cc4
Revises: 9fb6ea439420
Create Date: 2019-01-18 16:47:05.958132

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '94ebd7c19cc4'
down_revision = '9fb6ea439420'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('confirmation_requests')
    op.drop_table('faculty_confirmations')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('faculty_confirmations',
    sa.Column('project_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.Column('student_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['live_projects.id'], name='faculty_confirmations_ibfk_1'),
    sa.ForeignKeyConstraint(['student_id'], ['selecting_students.id'], name='faculty_confirmations_ibfk_2'),
    sa.PrimaryKeyConstraint('project_id', 'student_id'),
    mysql_default_charset='latin1',
    mysql_engine='InnoDB'
    )
    op.create_table('confirmation_requests',
    sa.Column('project_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.Column('student_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['live_projects.id'], name='confirmation_requests_ibfk_1'),
    sa.ForeignKeyConstraint(['student_id'], ['selecting_students.id'], name='confirmation_requests_ibfk_2'),
    sa.PrimaryKeyConstraint('project_id', 'student_id'),
    mysql_default_charset='latin1',
    mysql_engine='InnoDB'
    )
    # ### end Alembic commands ###
