"""Widen box_access_token and box_refresh_token columns from VARCHAR(255) to LONGTEXT.

Box OAuth tokens (especially access tokens after AES-GCM encryption + base64 encoding) can
exceed 255 characters, causing silent truncation and immediate 'invalid_grant' failures.

Revision ID: e8f9a0b1c2d3
Revises: d2e3f4a5b6c7
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa

revision = "e8f9a0b1c2d3"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "box_access_token",
            existing_type=sa.String(length=255, collation="utf8_bin"),
            type_=sa.Text(collation="utf8_bin"),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "box_refresh_token",
            existing_type=sa.String(length=255, collation="utf8_bin"),
            type_=sa.Text(collation="utf8_bin"),
            existing_nullable=True,
        )

    # Clear any previously-stored tokens that may have been silently truncated.
    # Users will be prompted to re-link their Box accounts on next export attempt.
    op.execute(
        "UPDATE users SET box_access_token = NULL, box_refresh_token = NULL, "
        "box_token_valid = 0 WHERE box_access_token IS NOT NULL OR box_refresh_token IS NOT NULL"
    )


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "box_access_token",
            existing_type=sa.Text(collation="utf8_bin"),
            type_=sa.String(length=255, collation="utf8_bin"),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "box_refresh_token",
            existing_type=sa.Text(collation="utf8_bin"),
            type_=sa.String(length=255, collation="utf8_bin"),
            existing_nullable=True,
        )
