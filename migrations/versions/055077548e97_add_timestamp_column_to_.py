"""Add 'timestamp' column to EmailNotification record

Revision ID: 055077548e97
Revises: 4e5c79f13c75
Create Date: 2019-04-12 23:10:12.788918

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '055077548e97'
down_revision = '4e5c79f13c75'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('email_notifications', sa.Column('timestamp', sa.DateTime(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('email_notifications', 'timestamp')
    # ### end Alembic commands ###
