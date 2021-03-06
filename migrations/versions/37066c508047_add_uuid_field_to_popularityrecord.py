"""Add UUID field to PopularityRecord

Revision ID: 37066c508047
Revises: 0636093f8aa0
Create Date: 2018-07-17 00:18:25.449850

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '37066c508047'
down_revision = '0636093f8aa0'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('popularity_record', sa.Column('uuid', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_popularity_record_uuid'), 'popularity_record', ['uuid'], unique=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_popularity_record_uuid'), table_name='popularity_record')
    op.drop_column('popularity_record', 'uuid')
    # ### end Alembic commands ###
