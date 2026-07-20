"""Change lp_file_id FK in matching_attempts and scheduling_attempts to ON DELETE SET NULL.

Without this, deleting an expired GeneratedAsset that is still referenced as an LP file
raises IntegrityError 1451.  The column is nullable, so SET NULL is the correct action.

Revision ID: d3e4f5a6b7c8
Revises: a9b8c7d6e5f4
Create Date: 2026-06-10
"""

import sqlalchemy as sa
from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None

_LOOKUP = sa.text(
    """
    SELECT CONSTRAINT_NAME
    FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME        = :table
      AND COLUMN_NAME       = :column
      AND REFERENCED_TABLE_NAME = :ref_table
    """
)


def _get_fk_name(conn, table, column, ref_table):
    row = conn.execute(_LOOKUP, {"table": table, "column": column, "ref_table": ref_table}).fetchone()
    if row is None:
        raise RuntimeError(f"FK on {table}.{column} -> {ref_table} not found in INFORMATION_SCHEMA")
    return row[0]


def upgrade():
    conn = op.get_bind()

    fk_matching = _get_fk_name(conn, "matching_attempts", "lp_file_id", "generated_assets")
    op.drop_constraint(fk_matching, "matching_attempts", type_="foreignkey")
    op.create_foreign_key(None, "matching_attempts", "generated_assets", ["lp_file_id"], ["id"], ondelete="SET NULL")

    fk_scheduling = _get_fk_name(conn, "scheduling_attempts", "lp_file_id", "generated_assets")
    op.drop_constraint(fk_scheduling, "scheduling_attempts", type_="foreignkey")
    op.create_foreign_key(None, "scheduling_attempts", "generated_assets", ["lp_file_id"], ["id"], ondelete="SET NULL")


def downgrade():
    conn = op.get_bind()

    # Introspect the auto-generated SET NULL constraint names and restore plain RESTRICT FKs.
    fk_matching = _get_fk_name(conn, "matching_attempts", "lp_file_id", "generated_assets")
    op.drop_constraint(fk_matching, "matching_attempts", type_="foreignkey")
    op.create_foreign_key(None, "matching_attempts", "generated_assets", ["lp_file_id"], ["id"])

    fk_scheduling = _get_fk_name(conn, "scheduling_attempts", "lp_file_id", "generated_assets")
    op.drop_constraint(fk_scheduling, "scheduling_attempts", type_="foreignkey")
    op.create_foreign_key(None, "scheduling_attempts", "generated_assets", ["lp_file_id"], ["id"])
