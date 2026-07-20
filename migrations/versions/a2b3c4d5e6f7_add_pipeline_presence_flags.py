#
# Created by David Seery on 08/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Add fine-grained pipeline presence flags and version columns to submission_record

Revision ID: a2b3c4d5e6f7
Revises: e5f6a7b8c9d0
Create Date: 2026-05-08

Adds eight columns to submission_record that allow individual pipeline outputs
(lexical statistics, LLM grading, LLM feedback, similarity chunk extraction)
to be tracked independently:

  stats_present              BOOLEAN NOT NULL DEFAULT FALSE
  stats_algorithm_version    INT NULL
  llm_grading_present        BOOLEAN NOT NULL DEFAULT FALSE
  llm_prompt_version         INT NULL
  llm_feedback_present       BOOLEAN NOT NULL DEFAULT FALSE
  llm_feedback_prompt_version INT NULL
  chunks_present             BOOLEAN NOT NULL DEFAULT FALSE
  chunks_prompt_version      INT NULL

Existing records keep all new flags at their defaults (False/NULL), correctly
reflecting that they pre-date fine-grained version tracking.  A subsequent
batch resubmission job can backfill records that have language_analysis_complete
= True but individual presence flags still at False.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a2b3c4d5e6f7"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("submission_records", schema=None) as batch_op:
        batch_op.add_column(sa.Column("stats_present", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("stats_algorithm_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("llm_grading_present", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("llm_prompt_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("llm_feedback_present", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("llm_feedback_prompt_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("chunks_present", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("chunks_prompt_version", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("submission_records", schema=None) as batch_op:
        batch_op.drop_column("chunks_prompt_version")
        batch_op.drop_column("chunks_present")
        batch_op.drop_column("llm_feedback_prompt_version")
        batch_op.drop_column("llm_feedback_present")
        batch_op.drop_column("llm_prompt_version")
        batch_op.drop_column("llm_grading_present")
        batch_op.drop_column("stats_algorithm_version")
        batch_op.drop_column("stats_present")
