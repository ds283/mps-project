"""Add fields to StudentBatch model

Revision ID: 48f58e461ffa
Revises: 2720bc86be69
Create Date: 2020-09-25 10:38:49.727842

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '48f58e461ffa'
down_revision = '2720bc86be69'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('batch_student', sa.Column('ignore_Y0', sa.Boolean(), nullable=True))
    op.add_column('batch_student', sa.Column('trust_registration', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('batch_student', 'trust_registration')
    op.drop_column('batch_student', 'ignore_Y0')
    # ### end Alembic commands ###