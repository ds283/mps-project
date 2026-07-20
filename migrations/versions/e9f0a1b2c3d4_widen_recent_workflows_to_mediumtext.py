"""Widen recent_workflows from TEXT to MEDIUMTEXT on llm_orchestration_job

Revision ID: e9f0a1b2c3d4
Revises: d6e7f8a9b0c1
Create Date: 2026-05-12

recent_workflows stores up to 20 JSON-serialised workflow entries. Each entry
contains per-step timing fields including peak_completion_tokens and
total_completion_tokens (added in commit 2daada37). With nine steps and ~12
fields each the payload now exceeds the 65 535-byte TEXT limit, causing
DataError on commit. MEDIUMTEXT raises the limit to 16 777 215 bytes.
"""

from alembic import op

revision = "e9f0a1b2c3d4"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE llm_orchestration_job MODIFY COLUMN recent_workflows MEDIUMTEXT CHARACTER SET utf8 COLLATE utf8_bin")


def downgrade():
    op.execute("ALTER TABLE llm_orchestration_job MODIFY COLUMN recent_workflows TEXT CHARACTER SET utf8 COLLATE utf8_bin")
