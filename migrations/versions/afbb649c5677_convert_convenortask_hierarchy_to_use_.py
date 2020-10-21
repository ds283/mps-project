"""Convert ConvenorTask hierarchy to use joined table inheritance

Revision ID: afbb649c5677
Revises: 93506c777913
Create Date: 2020-10-22 00:19:38.031727

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'afbb649c5677'
down_revision = '93506c777913'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('convenor_generic_tasks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=True),
    sa.Column('repeat', sa.Boolean(), nullable=True),
    sa.Column('repeat_interval', sa.Integer(), nullable=True),
    sa.Column('repeat_frequency', sa.Integer(), nullable=True),
    sa.Column('repeat_from_due_date', sa.Integer(), nullable=True),
    sa.Column('rollover', sa.Boolean(), nullable=True),
    sa.ForeignKeyConstraint(['id'], ['convenor_tasks.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['project_class_config.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('convenor_selector_tasks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['id'], ['convenor_tasks.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['selecting_students.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('convenor_submitter_task',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['id'], ['convenor_tasks.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['submitting_students.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.drop_table('project_tasks')
    op.drop_table('selector_tasks')
    op.drop_table('submitter_tasks')
    op.drop_column('convenor_tasks', 'repeat_interval')
    op.drop_column('convenor_tasks', 'repeat_from_due_date')
    op.drop_column('convenor_tasks', 'rollover')
    op.drop_column('convenor_tasks', 'repeat')
    op.drop_column('convenor_tasks', 'repeat_frequency')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('convenor_tasks', sa.Column('repeat_frequency', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True))
    op.add_column('convenor_tasks', sa.Column('repeat', mysql.TINYINT(display_width=1), autoincrement=False, nullable=True))
    op.add_column('convenor_tasks', sa.Column('rollover', mysql.TINYINT(display_width=1), autoincrement=False, nullable=True))
    op.add_column('convenor_tasks', sa.Column('repeat_from_due_date', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True))
    op.add_column('convenor_tasks', sa.Column('repeat_interval', mysql.TINYINT(display_width=1), autoincrement=False, nullable=True))
    op.create_table('submitter_tasks',
    sa.Column('submitter_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.Column('tasks_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['submitter_id'], ['submitting_students.id'], name='submitter_tasks_ibfk_1'),
    sa.ForeignKeyConstraint(['tasks_id'], ['convenor_tasks.id'], name='submitter_tasks_ibfk_2'),
    sa.PrimaryKeyConstraint('submitter_id', 'tasks_id'),
    mysql_default_charset='latin1',
    mysql_engine='InnoDB'
    )
    op.create_table('selector_tasks',
    sa.Column('selector_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.Column('tasks_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['selector_id'], ['selecting_students.id'], name='selector_tasks_ibfk_1'),
    sa.ForeignKeyConstraint(['tasks_id'], ['convenor_tasks.id'], name='selector_tasks_ibfk_2'),
    sa.PrimaryKeyConstraint('selector_id', 'tasks_id'),
    mysql_default_charset='latin1',
    mysql_engine='InnoDB'
    )
    op.create_table('project_tasks',
    sa.Column('config_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.Column('tasks_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['config_id'], ['project_class_config.id'], name='project_tasks_ibfk_1'),
    sa.ForeignKeyConstraint(['tasks_id'], ['convenor_tasks.id'], name='project_tasks_ibfk_2'),
    sa.PrimaryKeyConstraint('config_id', 'tasks_id'),
    mysql_default_charset='latin1',
    mysql_engine='InnoDB'
    )
    op.drop_table('convenor_submitter_task')
    op.drop_table('convenor_selector_tasks')
    op.drop_table('convenor_generic_tasks')
    # ### end Alembic commands ###
