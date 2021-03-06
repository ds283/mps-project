"""Add course code field to DegreeProgramme

Revision ID: 5fbaa40f20e9
Revises: d3bf7ff237de
Create Date: 2019-03-17 16:15:01.229771

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5fbaa40f20e9'
down_revision = 'd3bf7ff237de'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('degree_programmes', sa.Column('course_code', sa.String(length=255, collation='utf8_bin'), nullable=True))
    op.create_index(op.f('ix_degree_programmes_course_code'), 'degree_programmes', ['course_code'], unique=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_degree_programmes_course_code'), table_name='degree_programmes')
    op.drop_column('degree_programmes', 'course_code')
    # ### end Alembic commands ###
