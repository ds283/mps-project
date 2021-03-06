"""Add held field to EmailNotification model

Revision ID: b1cd6f33ee1e
Revises: 48f58e461ffa
Create Date: 2020-09-29 00:31:15.832341

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1cd6f33ee1e'
down_revision = '48f58e461ffa'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('email_notifications', sa.Column('held', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('email_notifications', 'held')
    # ### end Alembic commands ###
