#
# Created by David Seery on 24/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""matching: add infeasibility_report column to PuLPMixin

Revision ID: 6d4e2a9f1c73
Revises: 772a611e3122
Create Date: 2026-07-24

Adds a nullable JSON-encoded Text column to PuLPMixin (app/models/matching.py), which backs both
MatchingAttempt.matching_attempts and ScheduleAttempt.scheduling_attempts. Populated by
_diagnose_infeasibility() (app/tasks/matching.py) when the production solve returns infeasible.
See .prompts/matching-feasibility/PLAN.md §Phase 2.
"""

import sqlalchemy as sa
from alembic import op

revision = "6d4e2a9f1c73"
down_revision = "772a611e3122"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("matching_attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("infeasibility_report", sa.Text(collation="utf8_bin"), nullable=True))

    with op.batch_alter_table("scheduling_attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("infeasibility_report", sa.Text(collation="utf8_bin"), nullable=True))


def downgrade():
    with op.batch_alter_table("scheduling_attempts", schema=None) as batch_op:
        batch_op.drop_column("infeasibility_report")

    with op.batch_alter_table("matching_attempts", schema=None) as batch_op:
        batch_op.drop_column("infeasibility_report")
