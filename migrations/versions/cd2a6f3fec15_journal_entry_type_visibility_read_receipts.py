#
# Created by David Seery on 20/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""journal entry type, visibility flag, read-receipts

Revision ID: cd2a6f3fec15
Revises: f6a7b8c9d0e1
Create Date: 2026-07-20

Adds entry_type and restricted columns to student_journal_entries, and creates
the student_journal_entry_read association table recording which users have
read which journal entries.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "cd2a6f3fec15"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "student_journal_entries",
        sa.Column(
            "entry_type",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "student_journal_entries",
        sa.Column(
            "restricted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    op.create_table(
        "student_journal_entry_read",
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("read_timestamp", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["student_journal_entries.id"],
            name=op.f("fk_student_journal_entry_read_entry_id_student_journal_entries"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_student_journal_entry_read_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("entry_id", "user_id", name=op.f("pk_student_journal_entry_read")),
    )


def downgrade():
    op.drop_table("student_journal_entry_read")
    op.drop_column("student_journal_entries", "restricted")
    op.drop_column("student_journal_entries", "entry_type")
