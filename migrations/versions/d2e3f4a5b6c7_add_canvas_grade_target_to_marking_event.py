#
# Created by David Seery on 03/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Add canvas_grade_target to marking_event

Revision ID: d2e3f4a5b6c7
Revises: a7b8c9d0e1f2
Create Date: 2026-06-03

Adds MarkingEvent.canvas_grade_target: a locked Canvas grade target that is
set on the first confirmed push (bulk or per-student) and cleared on re-conflation.
This ensures all subsequent pushes within an event use a consistent target.
"""

import sqlalchemy as sa
from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "marking_events",
        sa.Column(
            "canvas_grade_target",
            sa.String(length=255, collation="utf8_bin"),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("marking_events", "canvas_grade_target")
