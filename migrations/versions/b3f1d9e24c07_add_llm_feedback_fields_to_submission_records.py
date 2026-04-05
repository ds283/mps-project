"""Add llm_feedback_failed and llm_feedback_failure_reason to submission_records

Revision ID: b3f1d9e24c07
Revises: a6e87998550d
Create Date: 2026-04-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3f1d9e24c07'
down_revision = 'a6e87998550d'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('submission_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('llm_feedback_failed', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('llm_feedback_failure_reason', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('submission_records', schema=None) as batch_op:
        batch_op.drop_column('llm_feedback_failure_reason')
        batch_op.drop_column('llm_feedback_failed')
