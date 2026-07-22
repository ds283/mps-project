#
# Created by David Seery on 22/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""encrypt ticket title, description and comment body at rest

Revision ID: f3b6d9a2c5e8
Revises: d4a9c7e2b8f5
Create Date: 2026-07-22

Retypes tickets.title, tickets.description and ticket_comments.body to the encrypted BLOB storage
used by EncryptedType/AesEngine (keyed by SQLALCHEMY_AES_KEY), and re-encrypts any existing rows in
place so no plaintext is lost. Data-preserving: plaintext is read first, the column is retyped, then
ciphertext is written back using the same EncryptedType bind processor the ORM uses, guaranteeing
round-trip compatibility. Requires an application context (as under `flask db upgrade`) so
get_AES_key() can read the key.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy_utils import EncryptedType
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine

from app.models.config import get_AES_key

revision = "f3b6d9a2c5e8"
down_revision = "d4a9c7e2b8f5"
branch_labels = None
depends_on = None


# (table, column, wrapped-type) for each field being encrypted
_FIELDS = [
    ("tickets", "title", sa.String(length=255, collation="utf8_bin")),
    ("tickets", "description", sa.Text()),
    ("ticket_comments", "body", sa.Text()),
]


def _encryptor(wrapped_type, dialect):
    enc = EncryptedType(wrapped_type, get_AES_key, AesEngine, "oneandzeroes")
    return lambda value: enc.process_bind_param(value, dialect)


def _decryptor(wrapped_type, dialect):
    enc = EncryptedType(wrapped_type, get_AES_key, AesEngine, "oneandzeroes")
    return lambda value: enc.process_result_value(value, dialect)


def _recode(convert, retype, nullable):
    conn = op.get_bind()
    dialect = conn.dialect
    for table, column, wrapped_type in _FIELDS:
        # capture current values before the type changes
        rows = conn.execute(sa.text(f"SELECT id, {column} FROM {table}")).fetchall()

        op.alter_column(table, column, type_=retype(), existing_nullable=nullable(column))

        transform = convert(wrapped_type, dialect)
        for row_id, value in rows:
            conn.execute(
                sa.text(f"UPDATE {table} SET {column} = :v WHERE id = :id"),
                {"v": transform(value), "id": row_id},
            )


def _is_nullable(column):
    # title is NOT NULL; description and body are nullable
    return column != "title"


def upgrade():
    _recode(_encryptor, sa.LargeBinary, _is_nullable)


def downgrade():
    # decrypt back to plaintext and restore the original column types
    conn = op.get_bind()
    dialect = conn.dialect
    restore_types = {
        "title": sa.String(length=255, collation="utf8_bin"),
        "description": sa.Text(collation="utf8_bin"),
        "body": sa.Text(collation="utf8_bin"),
    }
    for table, column, wrapped_type in _FIELDS:
        rows = conn.execute(sa.text(f"SELECT id, {column} FROM {table}")).fetchall()
        transform = _decryptor(wrapped_type, dialect)
        plain = {row_id: transform(value) for row_id, value in rows}

        op.alter_column(table, column, type_=restore_types[column], existing_nullable=_is_nullable(column))

        for row_id, value in plain.items():
            conn.execute(
                sa.text(f"UPDATE {table} SET {column} = :v WHERE id = :id"),
                {"v": value, "id": row_id},
            )
