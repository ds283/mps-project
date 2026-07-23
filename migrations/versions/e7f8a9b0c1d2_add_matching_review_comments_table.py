#
# Created by David Seery on 23/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""add matching_review_comments table

Revision ID: e7f8a9b0c1d2
Revises: 7fddffd79190
Create Date: 2026-07-23

Adds the MatchingReviewComment model backing the Matching Workspace review-comments panel
(Phase 6, .prompts/matching-workspace/PLAN.md): comments scoped either to a whole MatchingAttempt
(matching_record_id NULL) or to a single MatchingRecord, threaded one level via a self-referential
parent_id, and independently resolvable. body is stored via EncryptedType/AesEngine, matching the
ticket_comments.body encoding (LargeBinary at rest), since comment text may contain free-form,
potentially sensitive student detail.

Originally chained directly off b4e7a1d9c3f2 (the tip at the time this migration was written);
re-pointed at 7fddffd79190 (add ticket_subjects tombstone columns) after that unrelated migration
was merged from another branch onto the same base, forking the chain. The two touch disjoint
tables, so linearising here is safe.
"""

import sqlalchemy as sa
from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "7fddffd79190"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "matching_review_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("matching_attempt_id", sa.Integer(), nullable=False),
        sa.Column("matching_record_id", sa.Integer(), nullable=True),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("body", sa.LargeBinary(), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("resolved_by_id", sa.Integer(), nullable=True),
        sa.Column("resolved_timestamp", sa.DateTime(), nullable=True),
        sa.Column("creation_timestamp", sa.DateTime(), nullable=True),
        sa.Column("last_edit_timestamp", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["matching_attempt_id"],
            ["matching_attempts.id"],
            name=op.f("fk_matching_review_comments_matching_attempt_id_matching_attempts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["matching_record_id"],
            ["matching_records.id"],
            name=op.f("fk_matching_review_comments_matching_record_id_matching_records"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["matching_review_comments.id"],
            name=op.f("fk_matching_review_comments_parent_id_matching_review_comments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_matching_review_comments_owner_id_users")),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], name=op.f("fk_matching_review_comments_resolved_by_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_matching_review_comments")),
    )
    op.create_index(op.f("ix_matching_review_comments_matching_attempt_id"), "matching_review_comments", ["matching_attempt_id"], unique=False)
    op.create_index(op.f("ix_matching_review_comments_matching_record_id"), "matching_review_comments", ["matching_record_id"], unique=False)
    op.create_index(op.f("ix_matching_review_comments_parent_id"), "matching_review_comments", ["parent_id"], unique=False)
    op.create_index(op.f("ix_matching_review_comments_creation_timestamp"), "matching_review_comments", ["creation_timestamp"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_matching_review_comments_creation_timestamp"), table_name="matching_review_comments")
    op.drop_index(op.f("ix_matching_review_comments_parent_id"), table_name="matching_review_comments")
    op.drop_index(op.f("ix_matching_review_comments_matching_record_id"), table_name="matching_review_comments")
    op.drop_index(op.f("ix_matching_review_comments_matching_attempt_id"), table_name="matching_review_comments")
    op.drop_table("matching_review_comments")
