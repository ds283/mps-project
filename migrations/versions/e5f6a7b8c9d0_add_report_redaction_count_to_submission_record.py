"""Add report_redaction_count to submission_records

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-12 00:00:00.000000

Persists the number of times the student's name was automatically redacted from
the submitted PDF during processed-report generation. NULL means the report has
not yet been processed (or the submitted file was not a PDF).

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('submission_records', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('report_redaction_count', sa.Integer(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('submission_records', schema=None) as batch_op:
        batch_op.drop_column('report_redaction_count')
