"""Remove template_id from marking_workflows

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-05-19

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b6c7d8e9f0a1"
down_revision = "a5b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        "fk_marking_workflows_template_id_email_templates",
        "marking_workflows",
        type_="foreignkey",
    )
    op.drop_column("marking_workflows", "template_id")


def downgrade():
    op.add_column(
        "marking_workflows",
        sa.Column("template_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_marking_workflows_template_id_email_templates"),
        "marking_workflows",
        "email_templates",
        ["template_id"],
        ["id"],
    )
