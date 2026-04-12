"""Add ai_calibration column to tenants table

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-04-13 00:00:00.000000

Stores the per-tenant Mahalanobis calibration data for the AI concern
flagging system.  The column is a JSON text blob (schema documented in
Tenant.ai_calibration_data) and is initially NULL — the system will
surface a graceful "not yet calibrated" state until an admin runs the
calibration step.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ai_calibration", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        batch_op.drop_column("ai_calibration")
