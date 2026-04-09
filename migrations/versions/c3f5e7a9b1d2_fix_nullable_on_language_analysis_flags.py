"""Fix nullable on language-analysis flag columns

Revision ID: c3f5e7a9b1d2
Revises: b2e4f8a1c9d7
Create Date: 2026-04-09 00:00:00.000000

Make language_analysis_started, language_analysis_complete, and llm_analysis_failed
NOT NULL (backfilling any legacy NULLs to FALSE first).  These are binary yes/no flags
with no semantic value for NULL.

llm_feedback_failed is intentionally left nullable because it uses three-way semantics:
  NULL  = feedback task not yet attempted
  FALSE = feedback task ran and at least one chunk succeeded
  TRUE  = feedback task ran and all chunks failed (requires admin to clear for retry)

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'c3f5e7a9b1d2'
down_revision = 'b2e4f8a1c9d7'
branch_labels = None
depends_on = None


def upgrade():
    # Backfill any legacy NULLs before adding the NOT NULL constraint.
    # MySQL rejects ALTER COLUMN … NOT NULL when the column contains NULLs.
    op.execute(
        "UPDATE submission_records SET language_analysis_started = FALSE "
        "WHERE language_analysis_started IS NULL"
    )
    op.execute(
        "UPDATE submission_records SET language_analysis_complete = FALSE "
        "WHERE language_analysis_complete IS NULL"
    )
    op.execute(
        "UPDATE submission_records SET llm_analysis_failed = FALSE "
        "WHERE llm_analysis_failed IS NULL"
    )

    op.execute(
        "ALTER TABLE submission_records "
        "MODIFY COLUMN language_analysis_started BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE submission_records "
        "MODIFY COLUMN language_analysis_complete BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE submission_records "
        "MODIFY COLUMN llm_analysis_failed BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade():
    op.execute(
        "ALTER TABLE submission_records "
        "MODIFY COLUMN language_analysis_started BOOLEAN NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE submission_records "
        "MODIFY COLUMN language_analysis_complete BOOLEAN NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE submission_records "
        "MODIFY COLUMN llm_analysis_failed BOOLEAN NULL DEFAULT FALSE"
    )
