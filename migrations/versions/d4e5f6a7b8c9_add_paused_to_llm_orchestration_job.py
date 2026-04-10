"""Add paused flag to llm_orchestration_job

Revision ID: d4e5f6a7b8c9
Revises: c3f5e7a9b1d2
Create Date: 2026-04-10 00:00:00.000000

Add a per-job paused flag so that individual orchestration jobs can be temporarily
held (no new records dispatched) while other jobs continue to fill the batch slots.
Global pipeline pause is stored as a Redis key and requires no migration.

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'c3f5e7a9b1d2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('llm_orchestration_job', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('paused', sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade():
    with op.batch_alter_table('llm_orchestration_job', schema=None) as batch_op:
        batch_op.drop_column('paused')
