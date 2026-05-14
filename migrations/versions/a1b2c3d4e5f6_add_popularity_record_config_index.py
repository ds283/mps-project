"""Add composite index on popularity_record(config_id, liveproject_id, datestamp)

Revision ID: a1b2c3d4e5f6
Revises: f5b6c7d8e9a0
Create Date: 2026-05-14

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f5b6c7d8e9a0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_popularity_record_config_liveproject_datestamp",
        "popularity_record",
        ["config_id", "liveproject_id", "datestamp"],
    )


def downgrade():
    op.drop_index("ix_popularity_record_config_liveproject_datestamp", table_name="popularity_record")
