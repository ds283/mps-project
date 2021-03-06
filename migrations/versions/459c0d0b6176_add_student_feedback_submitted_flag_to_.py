"""Add student_feedback_submitted flag to SubmissionRecord

Revision ID: 459c0d0b6176
Revises: 4219c2076494
Create Date: 2018-09-07 23:46:37.707534

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '459c0d0b6176'
down_revision = '4219c2076494'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('submission_records', sa.Column('student_feedback_submitted', sa.Text(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('submission_records', 'student_feedback_submitted')
    # ### end Alembic commands ###
