"""Add uses_supervision_grade to period models and grade_push_log to MarkingEvent.

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-06-02

"""

import sqlalchemy as sa
from alembic import op

revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade():
    # ── SubmissionPeriodDefinition (period_definitions) ──────────────────────
    with op.batch_alter_table("period_definitions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "uses_supervision_grade",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    # ── SubmissionPeriodRecord (submission_periods) ───────────────────────────
    with op.batch_alter_table("submission_periods", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "uses_supervision_grade",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    # Data migration: mark any submission period that already has populated
    # supervision_grade values so that existing data remains visible.
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE submission_periods sp
            SET sp.uses_supervision_grade = TRUE
            WHERE EXISTS (
                SELECT 1 FROM submission_records sr
                WHERE sr.period_id = sp.id
                  AND sr.supervision_grade IS NOT NULL
            )
            """
        )
    )

    # ── MarkingEvent (marking_events) — grade-push audit log ─────────────────
    with op.batch_alter_table("marking_events", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "grade_push_log",
                sa.Text(collation="utf8_bin"),
                nullable=True,
            )
        )


def downgrade():
    with op.batch_alter_table("marking_events", schema=None) as batch_op:
        batch_op.drop_column("grade_push_log")

    with op.batch_alter_table("submission_periods", schema=None) as batch_op:
        batch_op.drop_column("uses_supervision_grade")

    with op.batch_alter_table("period_definitions", schema=None) as batch_op:
        batch_op.drop_column("uses_supervision_grade")
