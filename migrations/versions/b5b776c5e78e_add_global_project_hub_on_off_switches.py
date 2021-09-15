"""Add global Project Hub on/off switches

Revision ID: b5b776c5e78e
Revises: afbb649c5677
Create Date: 2020-10-23 17:06:18.963621

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b5b776c5e78e'
down_revision = 'afbb649c5677'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('project_class_config', sa.Column('use_project_hub', sa.Boolean(), nullable=True))
    op.add_column('project_classes', sa.Column('use_project_hub', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('project_classes', 'use_project_hub')
    op.drop_column('project_class_config', 'use_project_hub')
    # ### end Alembic commands ###
