#
# Created by David Seery on 07/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Create similarity_concerns table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-07

Creates the similarity_concerns table that backs the SimilarityConcern model.
Each row records a detected similarity concern between two SubmissionRecords
for a specific chunk type (abstract, introduction, etc.), always stored with
record_a_id < record_b_id (canonical ordering).  Reviewer workflow columns
allow concerns to be triaged and resolved.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "similarity_concerns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("record_a_id", sa.Integer(), nullable=False),
        sa.Column("record_b_id", sa.Integer(), nullable=False),
        sa.Column("chunk_type", sa.String(length=40, collation="utf8_bin"), nullable=False),
        sa.Column("minhash_jaccard", sa.Float(), nullable=True),
        sa.Column("transformer_cosine", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("resolution", sa.String(length=20, collation="utf8_bin"), nullable=True),
        sa.Column("resolution_note", sa.Text(collation="utf8_bin"), nullable=True),
        sa.ForeignKeyConstraint(["record_a_id"], ["submission_records.id"]),
        sa.ForeignKeyConstraint(["record_b_id"], ["submission_records.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_a_id", "record_b_id", "chunk_type", name="uq_similarity_concern"),
    )
    op.create_index(
        op.f("ix_similarity_concerns_record_a_id"),
        "similarity_concerns",
        ["record_a_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_similarity_concerns_record_b_id"),
        "similarity_concerns",
        ["record_b_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_similarity_concerns_record_b_id"), table_name="similarity_concerns")
    op.drop_index(op.f("ix_similarity_concerns_record_a_id"), table_name="similarity_concerns")
    op.drop_table("similarity_concerns")
