"""Add trust_cohort and academic_year fields to StudentBatch model

Revision ID: 6f30081a5119
Revises: 7ff0483513a2
Create Date: 2019-09-02 22:19:45.944570

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '6f30081a5119'
down_revision = '7ff0483513a2'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('live_project_to_classes')
    op.add_column('batch_student', sa.Column('academic_year', sa.Integer(), nullable=True))
    op.add_column('batch_student', sa.Column('trust_cohort', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('batch_student', 'trust_cohort')
    op.drop_column('batch_student', 'academic_year')
    op.create_table('live_project_to_classes',
    sa.Column('project_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.Column('project_class_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['project_class_id'], ['project_classes.id'], name='live_project_to_classes_ibfk_1'),
    sa.ForeignKeyConstraint(['project_id'], ['live_projects.id'], name='live_project_to_classes_ibfk_2'),
    sa.PrimaryKeyConstraint('project_id', 'project_class_id'),
    mysql_default_charset='latin1',
    mysql_engine='InnoDB'
    )
    # ### end Alembic commands ###
