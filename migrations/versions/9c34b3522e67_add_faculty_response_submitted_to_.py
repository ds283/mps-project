"""Add faculty_response_submitted to SubmissionRecord

Revision ID: 9c34b3522e67
Revises: 459c0d0b6176
Create Date: 2018-09-08 01:47:11.140593

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9c34b3522e67'
down_revision = '459c0d0b6176'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('submission_records', sa.Column('faculty_response_submitted', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('submission_records', 'faculty_response_submitted')
    # ### end Alembic commands ###
