"""Add abbreviation and colour fields to degree types/programmes

Revision ID: 460e67c2e023
Revises: bf2c30c6a77c
Create Date: 2018-09-18 23:29:32.443293

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '460e67c2e023'
down_revision = 'bf2c30c6a77c'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('degree_programmes', sa.Column('abbreviation', sa.String(length=255), nullable=True))
    op.add_column('degree_programmes', sa.Column('show_type', sa.Boolean(), nullable=True))
    op.create_index(op.f('ix_degree_programmes_abbreviation'), 'degree_programmes', ['abbreviation'], unique=False)
    op.add_column('degree_types', sa.Column('abbreviation', sa.String(length=255), nullable=True))
    op.add_column('degree_types', sa.Column('colour', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_degree_types_abbreviation'), 'degree_types', ['abbreviation'], unique=True)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_degree_types_abbreviation'), table_name='degree_types')
    op.drop_column('degree_types', 'colour')
    op.drop_column('degree_types', 'abbreviation')
    op.drop_index(op.f('ix_degree_programmes_abbreviation'), table_name='degree_programmes')
    op.drop_column('degree_programmes', 'show_type')
    op.drop_column('degree_programmes', 'abbreviation')
    # ### end Alembic commands ###
