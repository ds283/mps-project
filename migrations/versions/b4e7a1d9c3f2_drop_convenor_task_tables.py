#
# Created by David Seery on 23/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""drop convenor_task tables

Revision ID: b4e7a1d9c3f2
Revises: a1c4e7f0b3d6
Create Date: 2026-07-23

Phase 8 teardown (final step): drops the legacy ConvenorTask joined-table-inheritance schema
(convenor_tasks + its three subclass tables), now that the model classes have been removed from
the ORM and all data has been migrated into the Ticket system (see the Phase 8c data migration
and initdb.ensure_ticket_migration, itself removed once the migration had run everywhere).
tickets.source_task_id is a plain unconstrained int (not a FK to these tables), so there is no
ordering conflict with the ticket schema.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b4e7a1d9c3f2"
down_revision = "a1c4e7f0b3d6"
branch_labels = None
depends_on = None


def upgrade():
    # drop child (subclass) tables before the parent
    op.drop_table("convenor_generic_tasks")
    op.drop_table("convenor_selector_tasks")
    op.drop_table("convenor_submitter_tasks")
    op.drop_table("convenor_tasks")


def downgrade():
    op.create_table(
        "convenor_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("type", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("description", sa.String(length=255, collation="utf8_bin"), nullable=False),
        sa.Column("notes", sa.Text(collation="utf8_bin"), nullable=True),
        sa.Column("blocking", sa.Boolean(), nullable=True, server_default=sa.text("0")),
        sa.Column("complete", sa.Boolean(), nullable=True, server_default=sa.text("0")),
        sa.Column("dropped", sa.Boolean(), nullable=True, server_default=sa.text("0")),
        sa.Column("defer_date", sa.DateTime(), nullable=True),
        sa.Column("due_date", sa.DateTime(), nullable=True),
        sa.Column("creator_id", sa.Integer(), nullable=True),
        sa.Column("creation_timestamp", sa.DateTime(), nullable=True),
        sa.Column("last_edit_id", sa.Integer(), nullable=True),
        sa.Column("last_edit_timestamp", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"], name=op.f("fk_convenor_tasks_creator_id_users")),
        sa.ForeignKeyConstraint(["last_edit_id"], ["users.id"], name=op.f("fk_convenor_tasks_last_edit_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_convenor_tasks")),
    )
    op.create_index(op.f("ix_convenor_tasks_defer_date"), "convenor_tasks", ["defer_date"], unique=False)
    op.create_index(op.f("ix_convenor_tasks_due_date"), "convenor_tasks", ["due_date"], unique=False)

    op.create_table(
        "convenor_selector_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["id"], ["convenor_tasks.id"], name=op.f("fk_convenor_selector_tasks_id_convenor_tasks")),
        sa.ForeignKeyConstraint(["owner_id"], ["selecting_students.id"], name=op.f("fk_convenor_selector_tasks_owner_id_selecting_students")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_convenor_selector_tasks")),
    )

    op.create_table(
        "convenor_submitter_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["id"], ["convenor_tasks.id"], name=op.f("fk_convenor_submitter_tasks_id_convenor_tasks")),
        sa.ForeignKeyConstraint(["owner_id"], ["submitting_students.id"], name=op.f("fk_convenor_submitter_tasks_owner_id_submitting_students")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_convenor_submitter_tasks")),
    )

    op.create_table(
        "convenor_generic_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("repeat", sa.Boolean(), nullable=True, server_default=sa.text("0")),
        sa.Column("repeat_interval", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column("repeat_frequency", sa.Integer(), nullable=True),
        sa.Column("repeat_from_due_date", sa.Integer(), nullable=True, server_default=sa.text("1")),
        sa.Column("rollover", sa.Boolean(), nullable=True, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["id"], ["convenor_tasks.id"], name=op.f("fk_convenor_generic_tasks_id_convenor_tasks")),
        sa.ForeignKeyConstraint(["owner_id"], ["project_class_config.id"], name=op.f("fk_convenor_generic_tasks_owner_id_project_class_config")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_convenor_generic_tasks")),
    )
