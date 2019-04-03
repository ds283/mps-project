"""Add 'selector card text' fields to ProjectClass

Revision ID: 4e5c79f13c75
Revises: 383931c2a36d
Create Date: 2019-04-03 12:26:00.016340

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4e5c79f13c75'
down_revision = '383931c2a36d'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('project_classes', sa.Column('card_text_noninitial', sa.Text(), nullable=True))
    op.add_column('project_classes', sa.Column('card_text_normal', sa.Text(), nullable=True))
    op.add_column('project_classes', sa.Column('card_text_optional', sa.Text(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('project_classes', 'card_text_optional')
    op.drop_column('project_classes', 'card_text_normal')
    op.drop_column('project_classes', 'card_text_noninitial')
    # ### end Alembic commands ###
