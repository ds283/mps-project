"""Add lost, unattached, bucket, and comment fields to asset models

Revision ID: a0ae431e27dc
Revises: b8d1cfe3ee24
Create Date: 2023-09-05 10:39:24.827870

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a0ae431e27dc'
down_revision = 'b8d1cfe3ee24'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('generated_assets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lost', sa.Boolean(), nullable=False))
        batch_op.add_column(sa.Column('unattached', sa.Boolean(), nullable=False))
        batch_op.add_column(sa.Column('bucket', sa.Integer(), nullable=False))
        batch_op.add_column(sa.Column('comment', sa.Text(), nullable=True))

    with op.batch_alter_table('submitted_assets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lost', sa.Boolean(), nullable=False))
        batch_op.add_column(sa.Column('unattached', sa.Boolean(), nullable=False))
        batch_op.add_column(sa.Column('bucket', sa.Integer(), nullable=False))
        batch_op.add_column(sa.Column('comment', sa.Text(), nullable=True))

    with op.batch_alter_table('temporary_assets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lost', sa.Boolean(), nullable=False))
        batch_op.add_column(sa.Column('unattached', sa.Boolean(), nullable=False))
        batch_op.add_column(sa.Column('bucket', sa.Integer(), nullable=False))
        batch_op.add_column(sa.Column('comment', sa.Text(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('temporary_assets', schema=None) as batch_op:
        batch_op.drop_column('comment')
        batch_op.drop_column('bucket')
        batch_op.drop_column('unattached')
        batch_op.drop_column('lost')

    with op.batch_alter_table('submitted_assets', schema=None) as batch_op:
        batch_op.drop_column('comment')
        batch_op.drop_column('bucket')
        batch_op.drop_column('unattached')
        batch_op.drop_column('lost')

    with op.batch_alter_table('generated_assets', schema=None) as batch_op:
        batch_op.drop_column('comment')
        batch_op.drop_column('bucket')
        batch_op.drop_column('unattached')
        batch_op.drop_column('lost')

    # ### end Alembic commands ###