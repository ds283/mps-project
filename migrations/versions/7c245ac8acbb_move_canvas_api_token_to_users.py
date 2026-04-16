"""Move canvas_API_token from faculty_data to users; retarget canvas_login FK to users

Revision ID: 7c245ac8acbb
Revises: e2774dca7471
Create Date: 2026-04-17

Changes:
  - Add canvas_API_token column to users table (encrypted)
  - Copy existing token values from faculty_data to users (raw blob copy is safe:
    AesGcmEngine stores self-contained base64(nonce || ciphertext))
  - Drop canvas_API_token column from faculty_data
  - Retarget project_class_config.canvas_login_id FK from faculty_data.id to users.id
    (no data migration needed — FacultyData and User share primary keys)
"""
from alembic import op
import sqlalchemy as sa
import sqlalchemy_utils
from sqlalchemy import inspect as sa_inspect

revision = "7c245ac8acbb"
down_revision = "e2774dca7471"
branch_labels = None
depends_on = None


def _column_exists(table, column):
    inspector = sa_inspect(op.get_bind())
    return column in {c["name"] for c in inspector.get_columns(table)}


def _fk_for_column(table, column):
    """Return (name, referred_table) for the FK whose constrained column matches *column*, or (None, None)."""
    inspector = sa_inspect(op.get_bind())
    for fk in inspector.get_foreign_keys(table):
        if column in fk.get("constrained_columns", []):
            return fk.get("name"), fk.get("referred_table")
    return None, None


def upgrade():
    # 1. Add canvas_API_token to users (idempotent — step may have already run)
    if not _column_exists("users", "canvas_API_token"):
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "canvas_API_token",
                    sqlalchemy_utils.types.encrypted.encrypted_type.EncryptedType(),
                    nullable=True,
                )
            )

    # 2. Copy encrypted blobs from faculty_data to users only while faculty_data still
    #    has the column. The raw column value is self-contained (AesGcmEngine stores
    #    base64(nonce || ciphertext)), so a plain SQL copy is safe without re-encryption.
    if _column_exists("faculty_data", "canvas_API_token"):
        op.execute(
            """
            UPDATE users
            INNER JOIN faculty_data ON users.id = faculty_data.id
            SET users.canvas_API_token = faculty_data.canvas_API_token
            WHERE faculty_data.canvas_API_token IS NOT NULL
            """
        )

    # 3. Drop canvas_API_token from faculty_data (idempotent)
    if _column_exists("faculty_data", "canvas_API_token"):
        with op.batch_alter_table("faculty_data", schema=None) as batch_op:
            batch_op.drop_column("canvas_API_token")

    # 4. Retarget project_class_config.canvas_login_id FK from faculty_data to users.
    #    No data migration needed — FacultyData and User share the same primary key values.
    #    Use runtime inspection to find the actual constraint name, which may differ from
    #    what the initial migration recorded if the database pre-dated Flask-Migrate.
    fk_name, fk_referred = _fk_for_column("project_class_config", "canvas_login_id")
    with op.batch_alter_table("project_class_config", schema=None) as batch_op:
        if fk_name is not None and fk_referred == "faculty_data":
            batch_op.drop_constraint(fk_name, type_="foreignkey")
        batch_op.create_foreign_key(
            op.f("fk_project_class_config_canvas_login_id_users"),
            "users",
            ["canvas_login_id"],
            ["id"],
        )


def downgrade():
    # 4. Restore FK from users back to faculty_data
    fk_name, fk_referred = _fk_for_column("project_class_config", "canvas_login_id")
    with op.batch_alter_table("project_class_config", schema=None) as batch_op:
        if fk_name is not None and fk_referred == "users":
            batch_op.drop_constraint(fk_name, type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_project_class_config_canvas_login_id_faculty_data",
            "faculty_data",
            ["canvas_login_id"],
            ["id"],
        )

    # 3. Re-add canvas_API_token to faculty_data (idempotent)
    if not _column_exists("faculty_data", "canvas_API_token"):
        with op.batch_alter_table("faculty_data", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "canvas_API_token",
                    sqlalchemy_utils.types.encrypted.encrypted_type.EncryptedType(),
                    nullable=True,
                )
            )

    # 2. Copy tokens back from users to faculty_data (only faculty rows will match)
    if _column_exists("faculty_data", "canvas_API_token"):
        op.execute(
            """
            UPDATE faculty_data
            INNER JOIN users ON faculty_data.id = users.id
            SET faculty_data.canvas_API_token = users.canvas_API_token
            WHERE users.canvas_API_token IS NOT NULL
            """
        )

    # 1. Drop canvas_API_token from users (idempotent)
    if _column_exists("users", "canvas_API_token"):
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.drop_column("canvas_API_token")