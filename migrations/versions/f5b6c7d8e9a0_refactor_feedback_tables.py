#
# Created by David Seery on 26/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Refactor feedback tables

Revision ID: f5b6c7d8e9a0
Revises: e2774dca7471
Create Date: 2026-04-26

Drop legacy feedback tables and replace them with tables matching the
revised model in feedback.py:
  - Drop association tables: feedback_asset_to_pclasses, feedback_asset_to_tags,
    feedback_recipe_to_assets, feedback_recipe_to_pclasses
  - Drop main tables: feedback_recipes, feedback_assets, template_tags
  - Create feedback_template_tags (replaces template_tags; adds tenant_id)
  - Create feedback_assets (new schema: adds pclass_id, composite unique on pclass_id+label)
  - Create feedback_templates (new table)
  - Create feedback_recipes (new schema: adds pclass_id, composite unique on pclass_id+label)
  - Create feedback_template_to_tags (new association table)
  - Create feedback_recipe_to_assets (recreated association table)
  - feedback_reports is structurally unchanged and untouched
"""
from alembic import op
import sqlalchemy as sa

revision = "f5b6c7d8e9a0"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade():
    # --- Drop phase ---
    # Drop association tables first to satisfy FK constraints
    op.drop_table("feedback_asset_to_pclasses")
    op.drop_table("feedback_asset_to_tags")
    op.drop_table("feedback_recipe_to_assets")
    op.drop_table("feedback_recipe_to_pclasses")
    # Drop main tables
    op.drop_table("feedback_recipes")
    op.drop_table("feedback_assets")
    op.drop_table("template_tags")

    # --- Create phase ---

    # feedback_template_tags replaces template_tags
    # Has tenant_id (FK → tenants.id, indexed) + composite UniqueConstraint(tenant_id, name)
    # name also has unique=True at column level
    op.create_table(
        "feedback_template_tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255, collation="utf8_bin"), nullable=True),
        sa.Column("colour", sa.String(length=255, collation="utf8_bin"), nullable=True),
        sa.Column("creation_timestamp", sa.DateTime(), nullable=True),
        sa.Column("last_edit_timestamp", sa.DateTime(), nullable=True),
        sa.Column("creator_id", sa.Integer(), nullable=True),
        sa.Column("last_edit_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["users.id"],
            name=op.f("fk_feedback_template_tags_creator_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["last_edit_id"], ["users.id"],
            name=op.f("fk_feedback_template_tags_last_edit_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name=op.f("fk_feedback_template_tags_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback_template_tags")),
        sa.UniqueConstraint(
            "tenant_id", "name",
            name=op.f("uq_feedback_template_tags_tenant_id"),
        ),
        sa.UniqueConstraint("name", name=op.f("uq_feedback_template_tags_name")),
    )
    with op.batch_alter_table("feedback_template_tags", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_feedback_template_tags_tenant_id"), ["tenant_id"], unique=False
        )

    # feedback_assets — new schema adds pclass_id and composite unique constraint
    op.create_table(
        "feedback_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pclass_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("is_template", sa.Boolean(), nullable=True),
        sa.Column("label", sa.String(length=255, collation="utf8_bin"), nullable=True),
        sa.Column("description", sa.String(length=255, collation="utf8_bin"), nullable=True),
        sa.Column("creation_timestamp", sa.DateTime(), nullable=True),
        sa.Column("last_edit_timestamp", sa.DateTime(), nullable=True),
        sa.Column("creator_id", sa.Integer(), nullable=True),
        sa.Column("last_edit_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["submitted_assets.id"],
            name=op.f("fk_feedback_assets_asset_id_submitted_assets"),
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["users.id"],
            name=op.f("fk_feedback_assets_creator_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["last_edit_id"], ["users.id"],
            name=op.f("fk_feedback_assets_last_edit_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["pclass_id"], ["project_classes.id"],
            name=op.f("fk_feedback_assets_pclass_id_project_classes"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback_assets")),
        sa.UniqueConstraint(
            "pclass_id", "label",
            name=op.f("uq_feedback_assets_pclass_id"),
        ),
    )
    with op.batch_alter_table("feedback_assets", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_feedback_assets_label"), ["label"], unique=False
        )

    # feedback_templates — new table
    op.create_table(
        "feedback_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pclass_id", sa.Integer(), nullable=True),
        sa.Column("template_body", sa.Text(collation="utf8_bin"), nullable=True),
        sa.Column("label", sa.String(length=255, collation="utf8_bin"), nullable=True),
        sa.Column("description", sa.String(length=255, collation="utf8_bin"), nullable=True),
        sa.Column("creation_timestamp", sa.DateTime(), nullable=True),
        sa.Column("last_edit_timestamp", sa.DateTime(), nullable=True),
        sa.Column("creator_id", sa.Integer(), nullable=True),
        sa.Column("last_edit_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["users.id"],
            name=op.f("fk_feedback_templates_creator_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["last_edit_id"], ["users.id"],
            name=op.f("fk_feedback_templates_last_edit_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["pclass_id"], ["project_classes.id"],
            name=op.f("fk_feedback_templates_pclass_id_project_classes"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback_templates")),
        sa.UniqueConstraint(
            "pclass_id", "label",
            name=op.f("uq_feedback_templates_pclass_id"),
        ),
    )
    with op.batch_alter_table("feedback_templates", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_feedback_templates_label"), ["label"], unique=True
        )

    # feedback_recipes — new schema adds pclass_id + composite UniqueConstraint(pclass_id, label)
    # label also has index=True, unique=True at column level
    op.create_table(
        "feedback_recipes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pclass_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(length=255, collation="utf8_bin"), nullable=True),
        sa.Column("template_id", sa.Integer(), nullable=True),
        sa.Column("creation_timestamp", sa.DateTime(), nullable=True),
        sa.Column("last_edit_timestamp", sa.DateTime(), nullable=True),
        sa.Column("creator_id", sa.Integer(), nullable=True),
        sa.Column("last_edit_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["users.id"],
            name=op.f("fk_feedback_recipes_creator_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["last_edit_id"], ["users.id"],
            name=op.f("fk_feedback_recipes_last_edit_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["pclass_id"], ["project_classes.id"],
            name=op.f("fk_feedback_recipes_pclass_id_project_classes"),
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["feedback_templates.id"],
            name=op.f("fk_feedback_recipes_template_id_feedback_templates"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback_recipes")),
        sa.UniqueConstraint(
            "pclass_id", "label",
            name=op.f("uq_feedback_recipes_pclass_id"),
        ),
    )
    with op.batch_alter_table("feedback_recipes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_feedback_recipes_label"), ["label"], unique=True
        )

    # feedback_template_to_tags — new; FKs to feedback_templates + feedback_template_tags
    op.create_table(
        "feedback_template_to_tags",
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["template_id"], ["feedback_templates.id"],
            name=op.f("fk_feedback_template_to_tags_template_id_feedback_templates"),
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["feedback_template_tags.id"],
            name=op.f("fk_feedback_template_to_tags_tag_id_feedback_template_tags"),
        ),
        sa.PrimaryKeyConstraint(
            "template_id", "tag_id",
            name=op.f("pk_feedback_template_to_tags"),
        ),
    )

    # feedback_recipe_to_assets — recreated (same structure as before)
    op.create_table(
        "feedback_recipe_to_assets",
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["feedback_assets.id"],
            name=op.f("fk_feedback_recipe_to_assets_asset_id_feedback_assets"),
        ),
        sa.ForeignKeyConstraint(
            ["recipe_id"], ["feedback_recipes.id"],
            name=op.f("fk_feedback_recipe_to_assets_recipe_id_feedback_recipes"),
        ),
        sa.PrimaryKeyConstraint(
            "recipe_id", "asset_id",
            name=op.f("pk_feedback_recipe_to_assets"),
        ),
    )


def downgrade():
    pass
