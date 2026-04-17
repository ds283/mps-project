"""Add Box OAuth2 token fields to users table

Revision ID: a1b2c3d4e5f6
Revises: 7c245ac8acbb
Create Date: 2026-04-17

Changes:
  - Add box_access_token column to users table (encrypted TEXT, nullable)
  - Add box_refresh_token column to users table (encrypted TEXT, nullable)
  - Add box_token_valid column to users table (BOOLEAN, not null, default False)
  - Add box_updated_at column to users table (DATETIME, nullable)
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "7c245ac8acbb"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        # EncryptedType columns are stored as TEXT in the database; encryption
        # and decryption happen entirely in the Python layer.
        batch_op.add_column(sa.Column("box_access_token", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("box_refresh_token", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "box_token_valid",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("box_updated_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("box_updated_at")
        batch_op.drop_column("box_token_valid")
        batch_op.drop_column("box_refresh_token")
        batch_op.drop_column("box_access_token")
