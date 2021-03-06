"""Move number of assessors setting into SubmissionPeriodRecord

Revision ID: e04e704b2a6f
Revises: 6cbf362007eb
Create Date: 2018-12-10 00:06:04.931590

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'e04e704b2a6f'
down_revision = '6cbf362007eb'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('period_definitions', sa.Column('number_assessors', sa.Integer(), nullable=True))
    op.drop_column('presentation_assessments', 'number_assessors')
    op.add_column('submission_periods', sa.Column('number_assessors', sa.Integer(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('submission_periods', 'number_assessors')
    op.add_column('presentation_assessments', sa.Column('number_assessors', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True))
    op.drop_column('period_definitions', 'number_assessors')
    # ### end Alembic commands ###
