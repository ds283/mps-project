#
# Created by David Seery on 05/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Fix feedback label unique constraints

Revision ID: a0b1c2d3e4f5
Revises: f5b6c7d8e9a0
Create Date: 2026-05-05

feedback_templates.label and feedback_recipes.label were created with a
global unique index (unique=True on the column), in addition to the correct
per-pclass composite UniqueConstraint(pclass_id, label). The global index
is incorrect: labels only need to be unique within a project class.

Drop the global unique indexes and replace them with ordinary (non-unique)
indexes so that the same label can be used in different project classes.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "a0b1c2d3e4f5"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("feedback_templates", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_feedback_templates_label"))
        batch_op.create_index(batch_op.f("ix_feedback_templates_label"), ["label"], unique=False)

    with op.batch_alter_table("feedback_recipes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_feedback_recipes_label"))
        batch_op.create_index(batch_op.f("ix_feedback_recipes_label"), ["label"], unique=False)


def downgrade():
    with op.batch_alter_table("feedback_templates", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_feedback_templates_label"))
        batch_op.create_index(batch_op.f("ix_feedback_templates_label"), ["label"], unique=True)

    with op.batch_alter_table("feedback_recipes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_feedback_recipes_label"))
        batch_op.create_index(batch_op.f("ix_feedback_recipes_label"), ["label"], unique=True)
