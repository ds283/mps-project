"""Rename uploaded_assets model to temporary_assets

Revision ID: 7967c4e9136f
Revises: 6d4706c00935
Create Date: 2019-12-17 11:12:23.478065

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '7967c4e9136f'
down_revision = '6d4706c00935'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('temporary_assets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=True),
    sa.Column('lifetime', sa.Integer(), nullable=True),
    sa.Column('filename', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('acl_temporary',
    sa.Column('asset_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['temporary_assets.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('asset_id', 'user_id')
    )
    op.create_index(op.f('ix_temporary_assets_timestamp'), 'temporary_assets', ['timestamp'], unique=False)
    op.drop_index('ix_uploaded_assets_timestamp', table_name='uploaded_assets')
    op.drop_table('acl_uploaded')
    op.drop_table('uploaded_assets')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('uploaded_assets',
    sa.Column('id', mysql.INTEGER(display_width=11), autoincrement=True, nullable=False),
    sa.Column('timestamp', mysql.DATETIME(), nullable=True),
    sa.Column('lifetime', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True),
    sa.Column('filename', mysql.VARCHAR(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    mysql_default_charset='latin1',
    mysql_engine='InnoDB'
    )
    op.create_table('acl_uploaded',
    sa.Column('asset_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.Column('user_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['uploaded_assets.id'], name='acl_uploaded_ibfk_1'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='acl_uploaded_ibfk_2'),
    sa.PrimaryKeyConstraint('asset_id', 'user_id'),
    mysql_default_charset='latin1',
    mysql_engine='InnoDB'
    )
    op.create_index('ix_uploaded_assets_timestamp', 'uploaded_assets', ['timestamp'], unique=False)
    op.drop_index(op.f('ix_temporary_assets_timestamp'), table_name='temporary_assets')
    op.drop_table('acl_temporary')
    op.drop_table('temporary_assets')
    # ### end Alembic commands ###