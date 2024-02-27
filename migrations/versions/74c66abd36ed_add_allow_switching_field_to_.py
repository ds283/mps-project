"""Add allow_switching field to ProjectClass model

Revision ID: 74c66abd36ed
Revises: 727aa5a28800
Create Date: 2024-02-27 09:20:27.362710

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '74c66abd36ed'
down_revision = '727aa5a28800'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('project_classes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('allow_switching', sa.Boolean(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('project_classes', schema=None) as batch_op:
        batch_op.drop_column('allow_switching')

    # ### end Alembic commands ###
