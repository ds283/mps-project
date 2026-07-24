#
# Created by David Seery on 24/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""add per-record edit provenance to matching_records

Revision ID: f4a8c2e1b7d3
Revises: e7f8a9b0c1d2
Create Date: 2026-07-24

The Matching Workspace Changes tab attributes each changed row to a user and a timestamp, but
until now the only provenance available was attempt-level (matching_attempts.last_edit_id /
last_edit_timestamp), so every row of the table showed the same editor and time regardless of who
actually touched which record. These columns carry the same information per MatchingRecord; they
are written by MatchingRecord.mark_edited() and cleared by MatchingRecord.clear_edited() when a
record is reverted to its optimizer baseline.

There is deliberately no creator_id/creation_timestamp pair (i.e. EditingMetadataMixin is not
used): a MatchingRecord is always created by the optimizer run that owns it, so per-record
creation metadata would just duplicate the owning MatchingAttempt.

Existing rows backfill as NULL, which the Changes tab renders as an em dash rather than falling
back to the misleading attempt-level value.
"""

import sqlalchemy as sa
from alembic import op

revision = "f4a8c2e1b7d3"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("matching_records", sa.Column("last_edit_id", sa.Integer(), nullable=True))
    op.add_column("matching_records", sa.Column("last_edit_timestamp", sa.DateTime(), nullable=True))
    op.create_foreign_key(
        op.f("fk_matching_records_last_edit_id_users"),
        "matching_records",
        "users",
        ["last_edit_id"],
        ["id"],
    )


def downgrade():
    op.drop_constraint(op.f("fk_matching_records_last_edit_id_users"), "matching_records", type_="foreignkey")
    op.drop_column("matching_records", "last_edit_timestamp")
    op.drop_column("matching_records", "last_edit_id")
