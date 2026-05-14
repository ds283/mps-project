"""Add immutable uuid field to user table

Revision ID: b0c1d2e3f4a5
Revises: a4b5c6d7e8f9
Create Date: 2026-05-14

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b0c1d2e3f4a5"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade():
    # Add column as nullable first so existing rows can be backfilled.
    op.add_column(
        "users",
        sa.Column("uuid", sa.String(36, collation="utf8_bin"), nullable=True),
    )

    # Backfill existing rows using MySQL's UUID() function, which produces
    # the canonical xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx format.
    op.execute("UPDATE users SET uuid = UUID()")

    # Now enforce NOT NULL and add a unique index.
    op.alter_column("users", "uuid", nullable=False)
    op.create_index("ix_users_uuid", "users", ["uuid"], unique=True)


def downgrade():
    op.drop_index("ix_users_uuid", table_name="users")
    op.drop_column("users", "uuid")
