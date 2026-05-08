#
# Created by David Seery on 08/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Add error_log and recent_workflows to llm_orchestration_job

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-08

error_log stores a JSON-serialised list of structured error entries for each
LLMOrchestrationJob, capped at 100 entries.  Each entry captures the
timestamp, SubmissionRecord identity (id, student name, project class, year),
pipeline stage, exception type, and message.

recent_workflows stores a JSON-serialised list of the last 20 completed or
failed record workflows, containing per-step timing data reconstructed from
Redis after each record finishes.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "llm_orchestration_job",
        sa.Column("error_log", sa.Text(collation="utf8_bin"), nullable=True),
    )
    op.add_column(
        "llm_orchestration_job",
        sa.Column("recent_workflows", sa.Text(collation="utf8_bin"), nullable=True),
    )


def downgrade():
    op.drop_column("llm_orchestration_job", "recent_workflows")
    op.drop_column("llm_orchestration_job", "error_log")
