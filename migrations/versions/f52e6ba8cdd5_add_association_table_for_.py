"""Add association table for SubmissionPeriodRecords to PresentationAssessment

Revision ID: f52e6ba8cdd5
Revises: 29436496e921
Create Date: 2018-09-28 01:14:51.875272

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f52e6ba8cdd5'
down_revision = '29436496e921'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('assessment_to_periods',
    sa.Column('assessment_id', sa.Integer(), nullable=False),
    sa.Column('period_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['assessment_id'], ['presentation_assessments.id'], ),
    sa.ForeignKeyConstraint(['period_id'], ['submission_periods.id'], ),
    sa.PrimaryKeyConstraint('assessment_id', 'period_id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('assessment_to_periods')
    # ### end Alembic commands ###
