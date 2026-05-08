#
# Created by David Seery on 08/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Add indexes to fix slow most_popular_projects query

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-05-08

Adds:
- ix_live_projects_config_id: index on live_projects.config_id (was missing despite being a common filter column)
- ix_popularity_record_liveproject_datestamp: composite index on popularity_record(liveproject_id, datestamp)
  to support the MAX(datestamp) GROUP BY subquery and the re-join in most_popular_projects()
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("live_projects") as batch_op:
        batch_op.create_index(batch_op.f("ix_live_projects_config_id"), ["config_id"], unique=False)

    with op.batch_alter_table("popularity_record") as batch_op:
        batch_op.create_index(
            "ix_popularity_record_liveproject_datestamp",
            ["liveproject_id", "datestamp"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("popularity_record") as batch_op:
        batch_op.drop_index("ix_popularity_record_liveproject_datestamp")

    with op.batch_alter_table("live_projects") as batch_op:
        batch_op.drop_index(batch_op.f("ix_live_projects_config_id"))
