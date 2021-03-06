"""Update availability_deadline field to Date type

Revision ID: 2abccc4fad56
Revises: 651654a95222
Create Date: 2018-10-04 11:43:50.974414

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '2abccc4fad56'
down_revision = '651654a95222'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('presentation_assessments', 'availability_deadline',
               existing_type=mysql.DATETIME(),
               type_=sa.Date(),
               existing_nullable=True)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('presentation_assessments', 'availability_deadline',
               existing_type=sa.Date(),
               type_=mysql.DATETIME(),
               existing_nullable=True)
    # ### end Alembic commands ###
