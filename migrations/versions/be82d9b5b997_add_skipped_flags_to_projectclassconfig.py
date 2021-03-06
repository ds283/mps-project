"""Add 'skipped' flags to ProjectClassConfig

Revision ID: be82d9b5b997
Revises: b18ca484142d
Create Date: 2020-02-14 20:34:09.798571

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'be82d9b5b997'
down_revision = 'b18ca484142d'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('project_class_config', sa.Column('requests_skipped', sa.Boolean(), nullable=True))
    op.add_column('project_class_config', sa.Column('requests_skipped_id', sa.Integer(), nullable=True))
    op.add_column('project_class_config', sa.Column('requests_skipped_timestamp', sa.DateTime(), nullable=True))
    op.create_foreign_key(None, 'project_class_config', 'users', ['requests_skipped_id'], ['id'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'project_class_config', type_='foreignkey')
    op.drop_column('project_class_config', 'requests_skipped_timestamp')
    op.drop_column('project_class_config', 'requests_skipped_id')
    op.drop_column('project_class_config', 'requests_skipped')
    # ### end Alembic commands ###
