"""Remove template_id from marking_workflows

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-05-19

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

# revision identifiers, used by Alembic.
revision = "b6c7d8e9f0a1"
down_revision = "a5b6c7d8e9f0"
branch_labels = None
depends_on = None


def _find_fk_name(conn, table: str, column: str, referred_table: str) -> str:
    for fk in sa_inspect(conn).get_foreign_keys(table):
        if column in fk["constrained_columns"] and fk["referred_table"] == referred_table:
            return fk["name"]
    raise ValueError(f"No FK from {table}.{column} → {referred_table} found")


def upgrade():
    conn = op.get_bind()
    fk_name = _find_fk_name(conn, "marking_workflows", "template_id", "email_templates")
    with op.batch_alter_table("marking_workflows", schema=None) as batch_op:
        batch_op.drop_constraint(fk_name, type_="foreignkey")
        batch_op.drop_column("template_id")


def downgrade():
    with op.batch_alter_table("marking_workflows", schema=None) as batch_op:
        batch_op.add_column(sa.Column("template_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            op.f("fk_marking_workflows_template_id_email_templates"),
            "email_templates",
            ["template_id"],
            ["id"],
        )
