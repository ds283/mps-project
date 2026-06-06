"""Change box_access_token and box_refresh_token columns from TEXT to LONGBLOB.

Root cause: sqlalchemy_utils EncryptedType uses LargeBinary as its impl and only
decrypts values when process_result_value receives bytes (i.e., from a BLOB column).
When the columns are TEXT/VARCHAR, MySQL returns strings, the bytes check fails, and
the raw AES-GCM ciphertext is returned instead of the plaintext token — causing Box
to reject every API request with 400 invalid_grant.

The canvas_API_token column is correctly typed as blob and works. These two columns
must match that pattern.

Revision ID: a9b8c7d6e5f4
Revises: e8f9a0b1c2d3
Create Date: 2026-06-06
"""

from alembic import op
import sqlalchemy as sa

revision = "a9b8c7d6e5f4"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "box_access_token",
            existing_type=sa.Text(collation="utf8_bin"),
            type_=sa.LargeBinary(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "box_refresh_token",
            existing_type=sa.Text(collation="utf8_bin"),
            type_=sa.LargeBinary(),
            existing_nullable=True,
        )

    # Clear any tokens stored as TEXT (unreadable ciphertext strings).
    # Users must re-link after this migration; tokens will then be stored
    # correctly as BLOB and decrypted properly on retrieval.
    op.execute(
        "UPDATE users SET box_access_token = NULL, box_refresh_token = NULL, "
        "box_token_valid = 0 WHERE box_access_token IS NOT NULL OR box_refresh_token IS NOT NULL"
    )


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "box_access_token",
            existing_type=sa.LargeBinary(),
            type_=sa.Text(collation="utf8_bin"),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "box_refresh_token",
            existing_type=sa.LargeBinary(),
            type_=sa.Text(collation="utf8_bin"),
            existing_nullable=True,
        )
