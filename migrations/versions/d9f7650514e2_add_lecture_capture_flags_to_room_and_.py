"""Add lecture capture flags to Room and SubmissionPeriodDefinition, SubmissionPeriodRecord

Revision ID: d9f7650514e2
Revises: 2cb6081faa29
Create Date: 2018-10-26 21:57:52.273981

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd9f7650514e2'
down_revision = '2cb6081faa29'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('period_definitions', sa.Column('lecture_capture', sa.Boolean(), nullable=True))
    op.add_column('rooms', sa.Column('lecture_capture', sa.Boolean(), nullable=True))
    op.add_column('submission_periods', sa.Column('lecture_capture', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('submission_periods', 'lecture_capture')
    op.drop_column('rooms', 'lecture_capture')
    op.drop_column('period_definitions', 'lecture_capture')
    # ### end Alembic commands ###
