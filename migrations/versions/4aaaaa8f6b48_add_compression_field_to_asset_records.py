"""Add compression field to asset records

Revision ID: 4aaaaa8f6b48
Revises: 47081aac86f2
Create Date: 2023-10-08 23:25:05.227130

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4aaaaa8f6b48'
down_revision = '47081aac86f2'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('backups', schema=None) as batch_op:
        batch_op.add_column(sa.Column('compressed', sa.Boolean(), nullable=False))

    with op.batch_alter_table('generated_assets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('compressed', sa.Boolean(), nullable=False))

    with op.batch_alter_table('submitted_assets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('compressed', sa.Boolean(), nullable=False))

    with op.batch_alter_table('temporary_assets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('compressed', sa.Boolean(), nullable=False))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('temporary_assets', schema=None) as batch_op:
        batch_op.drop_column('compressed')

    with op.batch_alter_table('submitted_assets', schema=None) as batch_op:
        batch_op.drop_column('compressed')

    with op.batch_alter_table('generated_assets', schema=None) as batch_op:
        batch_op.drop_column('compressed')

    with op.batch_alter_table('backups', schema=None) as batch_op:
        batch_op.drop_column('compressed')

    # ### end Alembic commands ###
