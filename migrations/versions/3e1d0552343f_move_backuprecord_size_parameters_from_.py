"""Move BackupRecord size parameters from Integer to BigInteger

Revision ID: 3e1d0552343f
Revises: 055077548e97
Create Date: 2019-05-01 10:48:32.725608

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '3e1d0552343f'
down_revision = '055077548e97'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('backups', 'archive_size',
               existing_type=mysql.INTEGER(display_width=11),
               type_=sa.BigInteger(),
               existing_nullable=True)
    op.alter_column('backups', 'backup_size',
               existing_type=mysql.INTEGER(display_width=11),
               type_=sa.BigInteger(),
               existing_nullable=True)
    op.alter_column('backups', 'db_size',
               existing_type=mysql.INTEGER(display_width=11),
               type_=sa.BigInteger(),
               existing_nullable=True)
     # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('backups', 'db_size',
               existing_type=sa.BigInteger(),
               type_=mysql.INTEGER(display_width=11),
               existing_nullable=True)
    op.alter_column('backups', 'backup_size',
               existing_type=sa.BigInteger(),
               type_=mysql.INTEGER(display_width=11),
               existing_nullable=True)
    op.alter_column('backups', 'archive_size',
               existing_type=sa.BigInteger(),
               type_=mysql.INTEGER(display_width=11),
               existing_nullable=True)
    # ### end Alembic commands ###
