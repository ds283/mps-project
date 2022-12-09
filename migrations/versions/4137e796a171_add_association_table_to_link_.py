"""Add association table to link ProjectTag models to Project and LiveProject models

Revision ID: 4137e796a171
Revises: 81990828a0d5
Create Date: 2022-12-09 15:52:33.896151

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4137e796a171'
down_revision = '81990828a0d5'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('project_to_tags',
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('tag_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['tag_id'], ['project_tags.id'], ),
    sa.PrimaryKeyConstraint('project_id', 'tag_id')
    )
    op.create_table('live_project_to_tags',
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('tag_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['live_projects.id'], ),
    sa.ForeignKeyConstraint(['tag_id'], ['project_tags.id'], ),
    sa.PrimaryKeyConstraint('project_id', 'tag_id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('live_project_to_tags')
    op.drop_table('project_to_tags')
    # ### end Alembic commands ###
