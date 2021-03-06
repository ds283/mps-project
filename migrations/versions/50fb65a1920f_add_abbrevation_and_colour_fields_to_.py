"""Add abbrevation and colour fields to Supervisor

Revision ID: 50fb65a1920f
Revises: 3eea27e72afa
Create Date: 2018-08-28 11:45:47.279641

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '50fb65a1920f'
down_revision = '3eea27e72afa'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('supervision_team', sa.Column('abbreviation', sa.String(length=255), nullable=True))
    op.add_column('supervision_team', sa.Column('colour', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_supervision_team_abbreviation'), 'supervision_team', ['abbreviation'], unique=True)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_supervision_team_abbreviation'), table_name='supervision_team')
    op.drop_column('supervision_team', 'colour')
    op.drop_column('supervision_team', 'abbreviation')
    # ### end Alembic commands ###
