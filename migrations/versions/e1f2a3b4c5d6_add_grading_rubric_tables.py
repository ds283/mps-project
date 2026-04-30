#
# Created by David Seery on 30/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Add grading rubric tables

Revision ID: a1b2c3d4e5f6
Revises: f5b6c7d8e9a0
Create Date: 2026-04-30

Add three new tables for the database-backed grading rubric:
  - grading_rubric: top-level rubric, linked to a ProjectClass
  - rubric_band: grade band rows, ordered by position, FK to grading_rubric
  - rubric_criterion: individual criteria, ordered by position, FK to rubric_band

Also add grading_rubric_id (nullable FK) to project_class_config so each
ProjectClassConfig can reference the rubric to use for language analysis.
"""
from alembic import op
import sqlalchemy as sa

revision = "e1f2a3b4c5d6"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "grading_rubric",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pclass_id", sa.Integer(), sa.ForeignKey("project_classes.id"), nullable=False),
        sa.Column("label", sa.String(length=255, collation="utf8_bin"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pclass_id", "label"),
    )

    op.create_table(
        "rubric_band",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rubric_id", sa.Integer(), sa.ForeignKey("grading_rubric.id"), nullable=False),
        sa.Column("label", sa.String(length=255, collation="utf8_bin"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "rubric_criterion",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("band_id", sa.Integer(), sa.ForeignKey("rubric_band.id"), nullable=False),
        sa.Column("text", sa.Text(collation="utf8_bin"), nullable=False),
        sa.Column(
            "tag",
            sa.String(length=20, collation="utf8_bin"),
            nullable=False,
            server_default=sa.text("'plain'"),
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("project_class_config", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "grading_rubric_id",
                sa.Integer(),
                sa.ForeignKey("grading_rubric.id"),
                nullable=True,
            )
        )


def downgrade():
    with op.batch_alter_table("project_class_config", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_project_class_config_grading_rubric_id_grading_rubric",
            type_="foreignkey",
        )
        batch_op.drop_column("grading_rubric_id")

    op.drop_table("rubric_criterion")
    op.drop_table("rubric_band")
    op.drop_table("grading_rubric")
