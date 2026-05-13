#
# Created by David Seery on 13/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Add trigger flags and embedding_model to similarity_concerns

Revision ID: f1a2b3c4d5e6
Revises: e9f0a1b2c3d4
Create Date: 2026-05-13

Adds three columns to similarity_concerns:
  jaccard_triggered  — concern was triggered by MinHash Jaccard >= threshold
  cosine_triggered   — concern was triggered by cosine similarity >= per-chunk threshold
  embedding_model    — name of the sentence-transformers model used for cosine similarity

Both metrics now run independently; a concern is created when either fires.
Existing rows receive jaccard_triggered=False, cosine_triggered=False so that
they are visually distinguishable from rows produced by the new pipeline.
"""

import sqlalchemy as sa
from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "similarity_concerns",
        sa.Column(
            "jaccard_triggered",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "similarity_concerns",
        sa.Column(
            "cosine_triggered",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "similarity_concerns",
        sa.Column(
            "embedding_model",
            sa.String(length=100, collation="utf8_bin"),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("similarity_concerns", "embedding_model")
    op.drop_column("similarity_concerns", "cosine_triggered")
    op.drop_column("similarity_concerns", "jaccard_triggered")
