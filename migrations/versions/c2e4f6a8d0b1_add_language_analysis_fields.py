"""Add language analysis fields to submission_records

Revision ID: c2e4f6a8d0b1
Revises: b4c6d2e8f1a0
Create Date: 2026-04-03 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2e4f6a8d0b1'
down_revision = 'b4c6d2e8f1a0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('submission_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('language_analysis', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('language_analysis_started', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('language_analysis_complete', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('llm_analysis_failed', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('llm_failure_reason', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('submission_records', schema=None) as batch_op:
        batch_op.drop_column('llm_failure_reason')
        batch_op.drop_column('llm_analysis_failed')
        batch_op.drop_column('language_analysis_complete')
        batch_op.drop_column('language_analysis_started')
        batch_op.drop_column('language_analysis')
