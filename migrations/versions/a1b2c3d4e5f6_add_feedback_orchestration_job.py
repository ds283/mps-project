#
# Created by David Seery on 28/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Add feedback_orchestration_job table

Revision ID: a1b2c3d4e5f6
Revises: f5b6c7d8e9a0
Create Date: 2026-04-28

Creates the feedback_orchestration_job table used by FeedbackOrchestrationJob
to track bulk feedback PDF generation jobs orchestrated via Redis.
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "f5b6c7d8e9a0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "feedback_orchestration_job",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "uuid",
            sa.String(length=36, collation="utf8_bin"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("convenor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("marking_events.id"),
            nullable=True,
        ),
        sa.Column(
            "recipe_id",
            sa.Integer(),
            sa.ForeignKey("feedback_recipes.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20, collation="utf8_bin"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "description",
            sa.String(length=255, collation="utf8_bin"),
            nullable=True,
        ),
    )

    op.create_index(
        op.f("ix_feedback_orchestration_job_uuid"),
        "feedback_orchestration_job",
        ["uuid"],
        unique=True,
    )
    op.create_index(
        op.f("ix_feedback_orchestration_job_owner_id"),
        "feedback_orchestration_job",
        ["owner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feedback_orchestration_job_event_id"),
        "feedback_orchestration_job",
        ["event_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feedback_orchestration_job_recipe_id"),
        "feedback_orchestration_job",
        ["recipe_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feedback_orchestration_job_created_at"),
        "feedback_orchestration_job",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_feedback_orchestration_job_status"),
        "feedback_orchestration_job",
        ["status"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_feedback_orchestration_job_status"),
        table_name="feedback_orchestration_job",
    )
    op.drop_index(
        op.f("ix_feedback_orchestration_job_created_at"),
        table_name="feedback_orchestration_job",
    )
    op.drop_index(
        op.f("ix_feedback_orchestration_job_recipe_id"),
        table_name="feedback_orchestration_job",
    )
    op.drop_index(
        op.f("ix_feedback_orchestration_job_event_id"),
        table_name="feedback_orchestration_job",
    )
    op.drop_index(
        op.f("ix_feedback_orchestration_job_owner_id"),
        table_name="feedback_orchestration_job",
    )
    op.drop_index(
        op.f("ix_feedback_orchestration_job_uuid"),
        table_name="feedback_orchestration_job",
    )
    op.drop_table("feedback_orchestration_job")
