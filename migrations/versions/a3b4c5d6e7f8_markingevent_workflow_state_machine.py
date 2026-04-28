#
# Created by David Seery on 27/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""MarkingEvent workflow state machine

Revision ID: a3b4c5d6e7f8
Revises: f5b6c7d8e9a0
Create Date: 2026-04-27

Replace three boolean columns on marking_events (open, completed, closed) with a single
workflow_state integer column backed by MarkingEventWorkflowStates.

  WAITING = 0   (was open=False, completed=False, closed=False)
  OPEN    = 10  (was open=True,  completed=False, closed=False)
  READY_TO_CONFLATE         = 20  (was completed=True)
  READY_TO_GENERATE_FEEDBACK = 30  (new)
  READY_TO_PUSH_FEEDBACK     = 40  (new)
  CLOSED  = 100 (was closed=True)

Also move feedback-tracking fields from submitter_reports to conflation_reports:
  - Drop association tables: submitter_feedback_to_email_log,
    submitter_report_to_feedback_report
  - Drop columns from submitter_reports: feedback_sent, feedback_push_id,
    feedback_push_timestamp
  - Create association tables: conflation_report_to_email_log,
    conflation_report_to_feedback_report
  - Add columns to conflation_reports: feedback_sent, feedback_push_id,
    feedback_push_timestamp
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision = "a3b4c5d6e7f8"
down_revision = "dc092f0e28b4"
branch_labels = None
depends_on = None

# State constants (mirrored here so the migration is self-contained)
_WAITING = 0
_OPEN = 10
_READY_TO_CONFLATE = 20
_CLOSED = 100


def _find_fk_name(conn, table: str, column: str, referred_table: str) -> str:
    for fk in sa_inspect(conn).get_foreign_keys(table):
        if column in fk["constrained_columns"] and fk["referred_table"] == referred_table:
            return fk["name"]
    raise ValueError(f"No FK from {table}.{column} → {referred_table} found")


def upgrade():
    # ── marking_events: add workflow_state ──────────────────────────────────
    with op.batch_alter_table("marking_events", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "workflow_state",
                sa.Integer(),
                nullable=False,
                server_default=str(_WAITING),
            )
        )

    # Data migration: map existing boolean columns → new integer state.
    # Priority: closed > completed > open > default (WAITING).
    op.execute(
        f"""
        UPDATE marking_events
        SET workflow_state = CASE
            WHEN closed    = 1 THEN {_CLOSED}
            WHEN completed = 1 THEN {_READY_TO_CONFLATE}
            WHEN open      = 1 THEN {_OPEN}
            ELSE {_WAITING}
        END
        """
    )

    # Drop the three boolean columns now that data is migrated.
    with op.batch_alter_table("marking_events", schema=None) as batch_op:
        batch_op.drop_column("open")
        batch_op.drop_column("completed")
        batch_op.drop_column("closed")

    # ── submitter_reports: drop old feedback columns and association tables ──
    op.drop_table("submitter_feedback_to_email_log")
    op.drop_table("submitter_report_to_feedback_report")

    conn = op.get_bind()
    sr_fk_name = _find_fk_name(conn, "submitter_reports", "feedback_push_id", "users")

    with op.batch_alter_table("submitter_reports", schema=None) as batch_op:
        batch_op.drop_column("feedback_sent")
        batch_op.drop_constraint(sr_fk_name, type_="foreignkey")
        batch_op.drop_column("feedback_push_id")
        batch_op.drop_column("feedback_push_timestamp")

    # ── conflation_reports: add feedback columns and association tables ──────
    with op.batch_alter_table("conflation_reports", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "feedback_sent",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column("feedback_push_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("feedback_push_timestamp", sa.DateTime(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_conflation_reports_feedback_push_id_users",
            "users",
            ["feedback_push_id"],
            ["id"],
        )

    op.create_table(
        "conflation_report_to_feedback_report",
        sa.Column(
            "conflation_report_id",
            sa.Integer(),
            sa.ForeignKey("conflation_reports.id"),
            primary_key=True,
        ),
        sa.Column(
            "feedback_report_id",
            sa.Integer(),
            sa.ForeignKey("feedback_reports.id"),
            primary_key=True,
        ),
    )

    op.create_table(
        "conflation_report_to_email_log",
        sa.Column(
            "conflation_report_id",
            sa.Integer(),
            sa.ForeignKey("conflation_reports.id"),
            primary_key=True,
        ),
        sa.Column(
            "email_log_id",
            sa.Integer(),
            sa.ForeignKey("email_log.id"),
            primary_key=True,
        ),
    )


def downgrade():
    # ── Drop new conflation_report feedback tables ───────────────────────────
    op.drop_table("conflation_report_to_email_log")
    op.drop_table("conflation_report_to_feedback_report")

    conn = op.get_bind()
    cr_fk_name = _find_fk_name(conn, "conflation_reports", "feedback_push_id", "users")

    with op.batch_alter_table("conflation_reports", schema=None) as batch_op:
        batch_op.drop_constraint(cr_fk_name, type_="foreignkey")
        batch_op.drop_column("feedback_push_timestamp")
        batch_op.drop_column("feedback_push_id")
        batch_op.drop_column("feedback_sent")

    # ── Re-create submitter_reports feedback columns and association tables ──
    with op.batch_alter_table("submitter_reports", schema=None) as batch_op:
        batch_op.add_column(sa.Column("feedback_sent", sa.Boolean(), nullable=True))
        batch_op.add_column(
            sa.Column("feedback_push_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("feedback_push_timestamp", sa.DateTime(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_submitter_reports_feedback_push_id_users",
            "users",
            ["feedback_push_id"],
            ["id"],
        )

    op.create_table(
        "submitter_report_to_feedback_report",
        sa.Column(
            "submitter_report_id",
            sa.Integer(),
            sa.ForeignKey("submitter_reports.id"),
            primary_key=True,
        ),
        sa.Column(
            "feedback_report_id",
            sa.Integer(),
            sa.ForeignKey("feedback_reports.id"),
            primary_key=True,
        ),
    )

    op.create_table(
        "submitter_feedback_to_email_log",
        sa.Column(
            "submitter_report_id",
            sa.Integer(),
            sa.ForeignKey("submitter_reports.id"),
            primary_key=True,
        ),
        sa.Column(
            "email_log_id",
            sa.Integer(),
            sa.ForeignKey("email_log.id"),
            primary_key=True,
        ),
    )

    # ── marking_events: restore three boolean columns ────────────────────────
    with op.batch_alter_table("marking_events", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("open", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column(
                "completed", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch_op.add_column(
            sa.Column(
                "closed", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )

    # Reverse data migration: reconstruct booleans from workflow_state.
    op.execute(
        f"""
        UPDATE marking_events
        SET
            open      = IF(workflow_state >= {_OPEN}  AND workflow_state < {_CLOSED}, 1, 0),
            completed = IF(workflow_state >= {_READY_TO_CONFLATE} AND workflow_state < {_CLOSED}, 1, 0),
            closed    = IF(workflow_state >= {_CLOSED}, 1, 0)
        """
    )

    with op.batch_alter_table("marking_events", schema=None) as batch_op:
        batch_op.drop_column("workflow_state")
