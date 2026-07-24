#
# Created by David Seery on 24/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""matching: add is_draft column to MatchingAttempt

Revision ID: 9f2a8b1c4d6e
Revises: 6d4e2a9f1c73
Create Date: 2026-07-24

Adds a Boolean flag to MatchingAttempt (app/models/matching.py) distinguishing a coarse
diagnostic-draft solution (produced by _diagnose_infeasibility() when the production solve is
infeasible) from a genuine solution. solution_usable is unaffected by this flag; it is used only
so views can label draft MatchingRecord/MatchingRole rows appropriately.
See .prompts/matching-feasibility/PLAN.md §Phase 2.
"""

import sqlalchemy as sa
from alembic import op

revision = "9f2a8b1c4d6e"
down_revision = "6d4e2a9f1c73"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("matching_attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_draft", sa.Boolean(), nullable=True, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("matching_attempts", schema=None) as batch_op:
        batch_op.drop_column("is_draft")
