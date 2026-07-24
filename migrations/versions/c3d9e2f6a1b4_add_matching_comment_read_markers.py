#
# Created by David Seery on 24/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""add matching_comment_read_markers

Revision ID: c3d9e2f6a1b4
Revises: f4a8c2e1b7d3
Create Date: 2026-07-24

The Matching Workspace review-comments panel distinguishes comments the current user has not yet
seen. This table records, per (user, matching attempt), the instant at which that user last had the
panel rendered for them; anything created after it is "new". The marker is stamped by a separate
POST fired once the panel body has been delivered, so the value used to compute the "new" flags is
the previous one and the flags are visible on the view that clears them.

One row per user/attempt, enforced by a unique constraint. Rows are removed with the attempt (or
the user) via ON DELETE CASCADE; there is nothing to backfill, since an absent marker simply means
"has never looked", which is the correct initial state.
"""

import sqlalchemy as sa
from alembic import op

revision = "c3d9e2f6a1b4"
down_revision = "f4a8c2e1b7d3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "matching_comment_read_markers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("matching_attempt_id", sa.Integer(), nullable=False),
        sa.Column("last_read_timestamp", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["matching_attempt_id"],
            ["matching_attempts.id"],
            name=op.f("fk_matching_comment_read_markers_matching_attempt_id_matching_attempts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_matching_comment_read_markers_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_matching_comment_read_markers")),
        sa.UniqueConstraint("user_id", "matching_attempt_id", name="uq_comment_read_marker_user_attempt"),
    )
    op.create_index(op.f("ix_matching_comment_read_markers_user_id"), "matching_comment_read_markers", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_matching_comment_read_markers_matching_attempt_id"), "matching_comment_read_markers", ["matching_attempt_id"], unique=False
    )


def downgrade():
    op.drop_index(op.f("ix_matching_comment_read_markers_matching_attempt_id"), table_name="matching_comment_read_markers")
    op.drop_index(op.f("ix_matching_comment_read_markers_user_id"), table_name="matching_comment_read_markers")
    op.drop_table("matching_comment_read_markers")
