"""Add unique_name field to Asset models

Revision ID: a75eaec38b23
Revises: 7de210df6c03
Create Date: 2023-08-02 23:57:02.395744

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a75eaec38b23'
down_revision = '7de210df6c03'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('generated_assets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unique_name', sa.String(length=255, collation='utf8_bin'), nullable=True))

    with op.batch_alter_table('submitted_assets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unique_name', sa.String(length=255, collation='utf8_bin'), nullable=True))

    with op.batch_alter_table('temporary_assets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unique_name', sa.String(length=255, collation='utf8_bin'), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('temporary_assets', schema=None) as batch_op:
        batch_op.drop_column('unique_name')

    with op.batch_alter_table('submitted_assets', schema=None) as batch_op:
        batch_op.drop_column('unique_name')

    with op.batch_alter_table('generated_assets', schema=None) as batch_op:
        batch_op.drop_column('unique_name')

    # ### end Alembic commands ###