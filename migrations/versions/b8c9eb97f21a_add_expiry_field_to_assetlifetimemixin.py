"""Add expiry field to AssetLifetimeMixin

Revision ID: b8c9eb97f21a
Revises: 6bbd9e9d68d2
Create Date: 2020-01-11 22:51:30.177737

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8c9eb97f21a'
down_revision = '6bbd9e9d68d2'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('generated_assets', sa.Column('expiry', sa.DateTime(), nullable=True))
    op.add_column('submitted_assets', sa.Column('expiry', sa.DateTime(), nullable=True))
    op.add_column('temporary_assets', sa.Column('expiry', sa.DateTime(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('temporary_assets', 'expiry')
    op.drop_column('submitted_assets', 'expiry')
    op.drop_column('generated_assets', 'expiry')
    # ### end Alembic commands ###