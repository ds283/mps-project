"""Add unique_name field to Asset models

Revision ID: 5996b58bb039
Revises: 7de210df6c03
Create Date: 2023-08-02 15:10:55.231365

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '5996b58bb039'
down_revision = '7de210df6c03'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('generated_assets', schema=None) as batch_op:
        batch_op.alter_column('unique_name',
               existing_type=mysql.VARCHAR(charset='utf8', collation='utf8_bin', length=255),
               nullable=True)

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
        batch_op.alter_column('unique_name',
               existing_type=mysql.VARCHAR(charset='utf8', collation='utf8_bin', length=255),
               nullable=False)

    # ### end Alembic commands ###
