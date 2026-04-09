"""Add LLM provenance columns to submission_records

Revision ID: b2e4f8a1c9d7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2e4f8a1c9d7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('submission_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('llm_model_name', sa.String(length=200, collation='utf8_bin'), nullable=True))
        batch_op.add_column(sa.Column('llm_context_size', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('llm_num_chunks', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('submission_records', schema=None) as batch_op:
        batch_op.drop_column('llm_num_chunks')
        batch_op.drop_column('llm_context_size')
        batch_op.drop_column('llm_model_name')
