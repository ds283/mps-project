"""Add local copies of use supervisor/marker/presentations flags in ProjectClassConfig

Revision ID: 428eea9fbcc6
Revises: f8b116a12922
Create Date: 2020-11-06 19:11:12.099655

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '428eea9fbcc6'
down_revision = 'f8b116a12922'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('project_class_config', sa.Column('display_marker', sa.Boolean(), nullable=True))
    op.add_column('project_class_config', sa.Column('display_presentations', sa.Boolean(), nullable=True))
    op.add_column('project_class_config', sa.Column('uses_marker', sa.Boolean(), nullable=True))
    op.add_column('project_class_config', sa.Column('uses_presentations', sa.Boolean(), nullable=True))
    op.add_column('project_class_config', sa.Column('uses_supervisor', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('project_class_config', 'uses_supervisor')
    op.drop_column('project_class_config', 'uses_presentations')
    op.drop_column('project_class_config', 'uses_marker')
    op.drop_column('project_class_config', 'display_presentations')
    op.drop_column('project_class_config', 'display_marker')
    # ### end Alembic commands ###
