#
# Created by David Seery on 07/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Add llm_chunking_failed fields and drop similarity_orchestration_job table

Revision ID: b2c3d4e5f6a7
Revises: a0b1c2d3e4f5
Create Date: 2026-05-07

Two new columns on submission_records surface LLM heading-classification
failures so they appear as a RISK_SIMILARITY_CHUNKING_FAILED risk factor:

  llm_chunking_failed          BOOLEAN  NOT NULL DEFAULT 0
  llm_chunking_failure_reason  TEXT(utf8_bin) NULL

The similarity_orchestration_job table is dropped: standalone similarity
rebuilds now dispatch LLMOrchestrationJob chains directly, so the separate
orchestration model is no longer needed.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # Add chunking-failure columns to submission_records
    # ------------------------------------------------------------------
    with op.batch_alter_table("submission_records", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "llm_chunking_failed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "llm_chunking_failure_reason",
                sa.Text(collation="utf8_bin"),
                nullable=True,
            )
        )

    # ------------------------------------------------------------------
    # Drop the now-redundant similarity_orchestration_job table
    # ------------------------------------------------------------------
    # op.drop_table("similarity_orchestration_job")


def downgrade():
    # ------------------------------------------------------------------
    # Recreate similarity_orchestration_job
    # ------------------------------------------------------------------
    # op.create_table(
    #     "similarity_orchestration_job",
    #     sa.Column("id", sa.Integer(), nullable=False),
    #     sa.Column("uuid", sa.String(length=36, collation="utf8_bin"), nullable=False),
    #     sa.Column("owner_id", sa.Integer(), nullable=True),
    #     sa.Column("created_at", sa.DateTime(), nullable=False),
    #     sa.Column("started_at", sa.DateTime(), nullable=True),
    #     sa.Column("finished_at", sa.DateTime(), nullable=True),
    #     sa.Column("status", sa.String(length=20, collation="utf8_bin"), nullable=False),
    #     sa.Column("scope", sa.String(length=20, collation="utf8_bin"), nullable=False),
    #     sa.Column("scope_id", sa.Integer(), nullable=True),
    #     sa.Column("clear_existing", sa.Boolean(), nullable=False),
    #     sa.Column("paused", sa.Boolean(), nullable=False),
    #     sa.Column("total_count", sa.Integer(), nullable=False),
    #     sa.Column("completed_count", sa.Integer(), nullable=False),
    #     sa.Column("failed_count", sa.Integer(), nullable=False),
    #     sa.Column("description", sa.String(length=255, collation="utf8_bin"), nullable=True),
    #     sa.Column("rebuild_mode", sa.Boolean(), nullable=False),
    #     sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
    #     sa.PrimaryKeyConstraint("id"),
    #     sa.UniqueConstraint("uuid"),
    # )
    # op.create_index(
    #     op.f("ix_similarity_orchestration_job_uuid"),
    #     "similarity_orchestration_job",
    #     ["uuid"],
    #     unique=True,
    # )
    # op.create_index(
    #     op.f("ix_similarity_orchestration_job_owner_id"),
    #     "similarity_orchestration_job",
    #     ["owner_id"],
    #     unique=False,
    # )
    # op.create_index(
    #     op.f("ix_similarity_orchestration_job_created_at"),
    #     "similarity_orchestration_job",
    #     ["created_at"],
    #     unique=False,
    # )
    # op.create_index(
    #     op.f("ix_similarity_orchestration_job_status"),
    #     "similarity_orchestration_job",
    #     ["status"],
    #     unique=False,
    # )
    # op.create_index(
    #     op.f("ix_similarity_orchestration_job_scope_id"),
    #     "similarity_orchestration_job",
    #     ["scope_id"],
    #     unique=False,
    # )

    # ------------------------------------------------------------------
    # Remove chunking-failure columns from submission_records
    # ------------------------------------------------------------------
    with op.batch_alter_table("submission_records", schema=None) as batch_op:
        batch_op.drop_column("llm_chunking_failure_reason")
        batch_op.drop_column("llm_chunking_failed")
