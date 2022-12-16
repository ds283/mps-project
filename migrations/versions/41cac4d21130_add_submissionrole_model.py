"""Add SubmissionRole model

Revision ID: 41cac4d21130
Revises: c03cea7f94e5
Create Date: 2022-12-16 00:41:52.569822

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '41cac4d21130'
down_revision = 'c03cea7f94e5'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('submission_roles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('submission_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('role', sa.Integer(), nullable=False),
    sa.Column('marking_email', sa.Boolean(), nullable=True),
    sa.Column('positive_feedback', sa.Text(), nullable=True),
    sa.Column('improvements_feedback', sa.Text(), nullable=True),
    sa.Column('submitted_feedback', sa.Boolean(), nullable=True),
    sa.Column('feedback_timestamp', sa.DateTime(), nullable=True),
    sa.Column('acknowledge_student', sa.Boolean(), nullable=True),
    sa.Column('response', sa.Text(), nullable=True),
    sa.Column('submitted_response', sa.Boolean(), nullable=True),
    sa.Column('response_timestamp', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['submission_id'], ['submission_records.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('submission_roles')
    # ### end Alembic commands ###