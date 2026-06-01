"""Add distribution_state enum and email_workflow_item_id FK to marking_reports

Replaces the bare distributed BOOLEAN column with a distribution_state INTEGER
enum (0=UNSENT, 1=EMAIL_QUEUED, 2=EMAIL_CONFIRMED, 3=NOT_REQUIRED, 4=EMAIL_FAILED)
and adds a nullable FK to email_workflow_items so in-flight state can be tracked.

Revision ID: c8d9e0f1a2b3
Revises: b6c7d8e9f0a1
Create Date: 2026-06-01

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

# revision identifiers, used by Alembic.
revision = "c8d9e0f1a2b3"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def _find_fk_name(conn, table: str, column: str, referred_table: str) -> str:
    for fk in sa_inspect(conn).get_foreign_keys(table):
        if column in fk["constrained_columns"] and fk["referred_table"] == referred_table:
            return fk["name"]
    raise ValueError(f"No FK from {table}.{column} → {referred_table} found")


def upgrade():
    conn = op.get_bind()

    with op.batch_alter_table("marking_reports", schema=None) as batch_op:
        # Add the new enum column (default 0 = UNSENT)
        batch_op.add_column(sa.Column("distribution_state", sa.Integer(), nullable=False, server_default="0"))
        # Add the in-flight item FK (nullable; DB-level SET NULL on item deletion)
        batch_op.add_column(sa.Column("email_workflow_item_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_marking_reports_email_workflow_item_id_email_workflow_items"),
            "email_workflow_items",
            ["email_workflow_item_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Data migration: treat existing distributed=True rows as EMAIL_CONFIRMED (2)
    op.execute("UPDATE marking_reports SET distribution_state = 2 WHERE distributed = 1")

    with op.batch_alter_table("marking_reports", schema=None) as batch_op:
        batch_op.drop_column("distributed")


def downgrade():
    conn = op.get_bind()

    with op.batch_alter_table("marking_reports", schema=None) as batch_op:
        batch_op.add_column(sa.Column("distributed", sa.Boolean(), nullable=False, server_default="0"))

    # Restore distributed=True for all states that counted as distributed (1, 2, 3)
    op.execute("UPDATE marking_reports SET distributed = 1 WHERE distribution_state IN (1, 2, 3)")

    conn = op.get_bind()
    fk_name = _find_fk_name(conn, "marking_reports", "email_workflow_item_id", "email_workflow_items")
    with op.batch_alter_table("marking_reports", schema=None) as batch_op:
        batch_op.drop_constraint(fk_name, type_="foreignkey")
        batch_op.drop_column("email_workflow_item_id")
        batch_op.drop_column("distribution_state")
