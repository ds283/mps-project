"""Add unique index to nonce fields

Revision ID: 47081aac86f2
Revises: 47e0877b0196
Create Date: 2023-10-08 22:32:24.104653

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '47081aac86f2'
down_revision = '47e0877b0196'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('backups', schema=None) as batch_op:
        batch_op.add_column(sa.Column('bucket', sa.Integer(), nullable=False, server_default="3"))
        batch_op.add_column(sa.Column('comment', sa.Text(), nullable=True))
        batch_op.create_unique_constraint('ix_backups_nonce', ['nonce'])

    with op.batch_alter_table('generated_assets', schema=None) as batch_op:
        batch_op.create_unique_constraint('ix_generated_assets_nonce', ['nonce'])

    with op.batch_alter_table('submitted_assets', schema=None) as batch_op:
        batch_op.create_unique_constraint('ix_submitted_assets_nonce', ['nonce'])

    with op.batch_alter_table('temporary_assets', schema=None) as batch_op:
        batch_op.create_unique_constraint('ix_temporary_assets_nonce', ['nonce'])

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('temporary_assets', schema=None) as batch_op:
        batch_op.drop_constraint('ix_temporary_assets_nonce', type_='unique')

    with op.batch_alter_table('submitted_assets', schema=None) as batch_op:
        batch_op.drop_constraint('ix_submitted_assets_nonce', type_='unique')

    with op.batch_alter_table('generated_assets', schema=None) as batch_op:
        batch_op.drop_constraint('ix_generated_assets_nonce', type_='unique')

    with op.batch_alter_table('backups', schema=None) as batch_op:
        batch_op.drop_constraint('ix_backups_nonce', type_='unique')
        batch_op.drop_column('comment')
        batch_op.drop_column('bucket')

    # ### end Alembic commands ###
