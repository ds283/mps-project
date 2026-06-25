#
# Created by David Seery on 25/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""add ObjectStoreBackupRecord table

Revision ID: f6a7b8c9d0e1
Revises: d2e4f6a8b0c2
Create Date: 2026-06-25

Creates the object_store_backup_records table that backs the
ObjectStoreBackupRecord model.  One row per (run, bucket) records the
outcome of each cloud-storage backup run executed by the Beat scheduler.
Rows from the same Beat execution share a run_id UUID.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "d2e4f6a8b0c2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "object_store_backup_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=255, collation="utf8_bin"), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("bucket_type", sa.Integer(), nullable=False),
        sa.Column("bucket_label", sa.String(length=255, collation="utf8_bin"), nullable=True),
        sa.Column("provider_name", sa.String(length=255, collation="utf8_bin"), nullable=False, server_default="box"),
        sa.Column("cloud_folder_ref", sa.String(length=255, collation="utf8_bin"), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("object_count_total", sa.Integer(), nullable=True),
        sa.Column("object_count_uploaded", sa.Integer(), nullable=True),
        sa.Column("object_count_skipped", sa.Integer(), nullable=True),
        sa.Column("object_count_deleted", sa.Integer(), nullable=True),
        sa.Column("object_count_orphaned", sa.Integer(), nullable=True),
        sa.Column("object_count_error", sa.Integer(), nullable=True),
        sa.Column("bytes_uploaded", sa.BigInteger(), nullable=True),
        sa.Column("error_detail", sa.Text(collation="utf8_bin"), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("upload_mode", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_object_store_backup_records_run_id"),
        "object_store_backup_records",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_object_store_backup_records_bucket_type"),
        "object_store_backup_records",
        ["bucket_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_object_store_backup_records_timestamp"),
        "object_store_backup_records",
        ["timestamp"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_object_store_backup_records_timestamp"), table_name="object_store_backup_records")
    op.drop_index(op.f("ix_object_store_backup_records_bucket_type"), table_name="object_store_backup_records")
    op.drop_index(op.f("ix_object_store_backup_records_run_id"), table_name="object_store_backup_records")
    op.drop_table("object_store_backup_records")
