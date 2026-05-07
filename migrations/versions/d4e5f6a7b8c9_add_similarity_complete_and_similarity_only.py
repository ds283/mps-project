#
# Created by David Seery on 07/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Add similarity_complete to submission_record and similarity_only to llm_orchestration_job

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-07

similarity_complete tracks whether the similarity pipeline (extract_chunks →
compute_minhash → run_similarity_check) has completed for a SubmissionRecord.
Distinct from language_analysis_complete, which is set by finalize_language_step
(step 5) *before* the similarity steps run (steps 6–8).  Allows a targeted
"run missing similarity" rebuild that skips records already checked.

similarity_only on LLMOrchestrationJob flags jobs that should dispatch only
the similarity sub-chain rather than the full LLM + similarity pipeline.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "submission_record",
        sa.Column(
            "similarity_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "llm_orchestration_job",
        sa.Column(
            "similarity_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    op.drop_column("llm_orchestration_job", "similarity_only")
    op.drop_column("submission_record", "similarity_complete")
