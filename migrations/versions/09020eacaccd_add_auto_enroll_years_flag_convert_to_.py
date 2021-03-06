"""Add auto_enroll_years flag, convert_to_submitter flag

Revision ID: 09020eacaccd
Revises: 1c9076103f7b
Create Date: 2019-02-18 21:48:59.587037

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '09020eacaccd'
down_revision = '1c9076103f7b'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('project_classes', sa.Column('auto_enroll_years', sa.Integer(), nullable=True))
    op.add_column('selecting_students', sa.Column('convert_to_submitter', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('selecting_students', 'convert_to_submitter')
    op.drop_column('project_classes', 'auto_enroll_years')
    # ### end Alembic commands ###
