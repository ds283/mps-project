"""Add max_group_project_types field to MatchingAttempt

Revision ID: 3b988293634e
Revises: 0b27ae643728
Create Date: 2023-04-04 09:43:05.484935

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3b988293634e'
down_revision = '0b27ae643728'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('matching_attempts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('max_different_group_projects', sa.Integer(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('matching_attempts', schema=None) as batch_op:
        batch_op.drop_column('max_different_group_projects')

    # ### end Alembic commands ###
