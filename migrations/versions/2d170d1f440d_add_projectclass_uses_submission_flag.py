"""Add ProjectClass.uses_submission flag

Revision ID: 2d170d1f440d
Revises: 219d17013224
Create Date: 2023-03-05 01:49:04.589070

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2d170d1f440d'
down_revision = '219d17013224'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('project_classes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('uses_submission', sa.Integer(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('project_classes', schema=None) as batch_op:
        batch_op.drop_column('uses_submission')

    # ### end Alembic commands ###