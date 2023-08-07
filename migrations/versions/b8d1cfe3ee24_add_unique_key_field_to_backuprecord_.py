"""Add unique_key field to BackupRecord model

Revision ID: b8d1cfe3ee24
Revises: 10222088c23c
Create Date: 2023-08-07 13:17:58.859797

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'b8d1cfe3ee24'
down_revision = '10222088c23c'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('backups', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unique_name', sa.String(length=255, collation='utf8_bin'), nullable=False))
        batch_op.create_unique_constraint(None, ['unique_name'])
        batch_op.drop_column('filename')

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('backups', schema=None) as batch_op:
        batch_op.add_column(sa.Column('filename', mysql.VARCHAR(charset='utf8', collation='utf8_bin', length=255), nullable=True))
        batch_op.drop_constraint(None, type_='unique')
        batch_op.drop_column('unique_name')

    # ### end Alembic commands ###
