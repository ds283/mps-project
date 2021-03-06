"""Break include_marking_emails flag into marker and supervisor components

Revision ID: 4f7b8c8a78f5
Revises: 7081d19f8047
Create Date: 2020-05-29 19:02:11.319101

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4f7b8c8a78f5'
down_revision = '7081d19f8047'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('period_attachments', sa.Column('include_marker_emails', sa.Boolean(), nullable=True))
    op.add_column('period_attachments', sa.Column('include_supervisor_emails', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('period_attachments', 'include_supervisor_emails')
    op.drop_column('period_attachments', 'include_marker_emails')
    # ### end Alembic commands ###
