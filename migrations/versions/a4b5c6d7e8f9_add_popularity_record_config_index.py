"""Add composite index on popularity_record(config_id, liveproject_id, datestamp)

Revision ID: a4b5c6d7e8f9
Revises: f1a2b3c4d5e6
Create Date: 2026-05-14

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a4b5c6d7e8f9"
down_revision = "f1a2b3c4d5e6"
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
