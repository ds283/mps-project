"""Drop 'keywords' field from Project and LiveProject

Revision ID: 8dcc485032db
Revises: 0a30e6431a33
Create Date: 2022-12-12 14:45:34.512439

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '8dcc485032db'
down_revision = '0a30e6431a33'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('live_projects', schema=None) as batch_op:
        batch_op.drop_column('keywords')

    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('keywords')

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('keywords', mysql.VARCHAR(charset='utf8', collation='utf8_bin', length=255), nullable=True))

    with op.batch_alter_table('live_projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('keywords', mysql.VARCHAR(charset='utf8', collation='utf8_bin', length=255), nullable=True))

    # ### end Alembic commands ###