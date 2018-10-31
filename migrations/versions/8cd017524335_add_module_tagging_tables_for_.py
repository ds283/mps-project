"""Add module tagging tables for ProjectDescription and LiveProject

Revision ID: 8cd017524335
Revises: 0ee5e23f4a85
Create Date: 2018-10-31 09:01:41.264050

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8cd017524335'
down_revision = '0ee5e23f4a85'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('description_to_modules',
    sa.Column('description_id', sa.Integer(), nullable=False),
    sa.Column('module_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['description_id'], ['descriptions.id'], ),
    sa.ForeignKeyConstraint(['module_id'], ['modules.id'], ),
    sa.PrimaryKeyConstraint('description_id', 'module_id')
    )
    op.create_table('live_project_to_modules',
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('module_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['module_id'], ['modules.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['live_projects.id'], ),
    sa.PrimaryKeyConstraint('project_id', 'module_id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('live_project_to_modules')
    op.drop_table('description_to_modules')
    # ### end Alembic commands ###
