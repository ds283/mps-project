"""Correct typo in acl_submitted table schema

Revision ID: 26a9afb3ba1e
Revises: 977544ec2513
Create Date: 2019-12-18 00:18:21.078512

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '26a9afb3ba1e'
down_revision = '977544ec2513'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('acl_submitted_ibfk_1', 'acl_submitted', type_='foreignkey')
    op.create_foreign_key(None, 'acl_submitted', 'submitted_assets', ['asset_id'], ['id'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'acl_submitted', type_='foreignkey')
    op.create_foreign_key('acl_submitted_ibfk_1', 'acl_submitted', 'temporary_assets', ['asset_id'], ['id'])
    # ### end Alembic commands ###
