"""Add editing metadata to ProjectDescription

Revision ID: 16407912c83e
Revises: 2d91da792f60
Create Date: 2018-08-27 21:36:26.551135

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '16407912c83e'
down_revision = '2d91da792f60'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('descriptions', sa.Column('creation_timestamp', sa.DateTime(), nullable=True))
    op.add_column('descriptions', sa.Column('creator_id', sa.Integer(), nullable=True))
    op.add_column('descriptions', sa.Column('last_edit_id', sa.Integer(), nullable=True))
    op.add_column('descriptions', sa.Column('last_edit_timestamp', sa.DateTime(), nullable=True))
    op.create_foreign_key(None, 'descriptions', 'users', ['creator_id'], ['id'])
    op.create_foreign_key(None, 'descriptions', 'users', ['last_edit_id'], ['id'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'descriptions', type_='foreignkey')
    op.drop_constraint(None, 'descriptions', type_='foreignkey')
    op.drop_column('descriptions', 'last_edit_timestamp')
    op.drop_column('descriptions', 'last_edit_id')
    op.drop_column('descriptions', 'creator_id')
    op.drop_column('descriptions', 'creation_timestamp')
    # ### end Alembic commands ###
