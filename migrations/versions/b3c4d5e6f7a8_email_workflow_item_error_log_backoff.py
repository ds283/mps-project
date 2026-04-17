"""Replace email workflow item error_message with timestamped error_log; add next_retry_time

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-04-17

Changes:
  - Drop error_message column from email_workflow_items
  - Add error_log column (TEXT, nullable) — JSON list of {timestamp, message} dicts
  - Add next_retry_time column (DATETIME, nullable, indexed) — per-item exponential backoff gate
"""
from alembic import op
import sqlalchemy as sa

revision = "b3c4d5e6f7a8"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("email_workflow_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("error_log", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("next_retry_time", sa.DateTime(), nullable=True))
        batch_op.create_index(
            "ix_email_workflow_items_next_retry_time",
            ["next_retry_time"],
            unique=False,
        )
        batch_op.drop_column("error_message")


def downgrade():
    with op.batch_alter_table("email_workflow_items", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "error_message",
                sa.String(length=255, collation="utf8_bin"),
                nullable=True,
            )
        )
        batch_op.drop_index("ix_email_workflow_items_next_retry_time")
        batch_op.drop_column("next_retry_time")
        batch_op.drop_column("error_log")
