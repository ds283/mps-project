"""Add SubmissionPeriodDefinition record

Revision ID: 6f96e65e8319
Revises: 33994cfc0340
Create Date: 2018-09-27 16:52:24.619735

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '6f96e65e8319'
down_revision = '33994cfc0340'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('period_definitions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=True),
    sa.Column('period', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=255, collation='utf8_bin'), nullable=True),
    sa.Column('has_presentation', sa.Boolean(), nullable=True),
    sa.Column('creator_id', sa.Integer(), nullable=True),
    sa.Column('creation_timestamp', sa.DateTime(), nullable=True),
    sa.Column('last_edit_id', sa.Integer(), nullable=True),
    sa.Column('last_edit_timestamp', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['creator_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['last_edit_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['project_classes.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.drop_column('project_classes', 'presentation_list')
    op.drop_column('project_classes', 'submissions')
    op.add_column('submission_periods', sa.Column('has_presentation', sa.Boolean(), nullable=True))
    op.add_column('submission_periods', sa.Column('name', sa.String(length=255), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('submission_periods', 'name')
    op.drop_column('submission_periods', 'has_presentation')
    op.add_column('project_classes', sa.Column('submissions', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True))
    op.add_column('project_classes', sa.Column('presentation_list', mysql.TEXT(), nullable=True))
    op.drop_table('period_definitions')
    # ### end Alembic commands ###
