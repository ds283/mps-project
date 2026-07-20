#
# Created by David Seery on 01/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""Add tenant_ai_calibrations table

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-05-01

Replaces the ai_calibration JSON blob column on the tenants table with a
first-class tenant_ai_calibrations table.  Each existing non-null blob is
migrated to a row with feature_set='lexical' and null LLM fields, then the
old column is dropped.
"""

import json

from alembic import op
import sqlalchemy as sa
from datetime import datetime

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tenant_ai_calibrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("calibrated_at", sa.DateTime(), nullable=False),
        sa.Column("n_samples", sa.Integer(), nullable=False),
        sa.Column("included_years", sa.Text(collation="utf8_bin"), nullable=True),
        sa.Column("included_pclass_ids", sa.Text(collation="utf8_bin"), nullable=True),
        sa.Column("llm_model_name", sa.String(length=255, collation="utf8_bin"), nullable=True),
        sa.Column("llm_context_window", sa.Integer(), nullable=True),
        sa.Column(
            "feature_set",
            sa.String(length=32, collation="utf8_bin"),
            nullable=False,
            server_default=sa.text("'lexical'"),
        ),
        sa.Column("mu", sa.Text(collation="utf8_bin"), nullable=False),
        sa.Column("sigma_inv", sa.Text(collation="utf8_bin"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "feature_set",
            "llm_model_name",
            "llm_context_window",
            name="uq_tenant_calibration",
        ),
    )

    # Data migration: read existing blobs and insert corresponding rows
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, ai_calibration FROM tenants WHERE ai_calibration IS NOT NULL")).fetchall()

    for tenant_id, blob in rows:
        try:
            data = json.loads(blob)
        except (json.JSONDecodeError, TypeError):
            continue

        calibrated_at_raw = data.get("calibrated_at")
        if calibrated_at_raw is None:
            continue
        try:
            calibrated_at = datetime.fromisoformat(calibrated_at_raw)
        except ValueError:
            continue

        n_samples = data.get("n_samples", 0)
        included_years = json.dumps(data.get("included_years", []))
        included_pclass_ids = json.dumps(data.get("included_pclass_ids", []))
        mu = json.dumps(data.get("mu", []))
        sigma_inv = json.dumps(data.get("sigma_inv", []))

        bind.execute(
            sa.text(
                "INSERT INTO tenant_ai_calibrations "
                "(tenant_id, feature_set, llm_model_name, llm_context_window, "
                " calibrated_at, n_samples, included_years, included_pclass_ids, mu, sigma_inv) "
                "VALUES (:tenant_id, 'lexical', NULL, NULL, "
                " :calibrated_at, :n_samples, :included_years, :included_pclass_ids, :mu, :sigma_inv)"
            ),
            {
                "tenant_id": tenant_id,
                "calibrated_at": calibrated_at,
                "n_samples": n_samples,
                "included_years": included_years,
                "included_pclass_ids": included_pclass_ids,
                "mu": mu,
                "sigma_inv": sigma_inv,
            },
        )

    with op.batch_alter_table("tenants", schema=None) as batch_op:
        batch_op.drop_column("ai_calibration")


def downgrade():
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ai_calibration", sa.Text(collation="utf8_bin"), nullable=True))

    # Restore blobs from lexical-only rows
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT tenant_id, calibrated_at, n_samples, included_years, included_pclass_ids, mu, sigma_inv "
            "FROM tenant_ai_calibrations "
            "WHERE feature_set = 'lexical' AND llm_model_name IS NULL"
        )
    ).fetchall()

    for row in rows:
        tenant_id, calibrated_at, n_samples, included_years, included_pclass_ids, mu, sigma_inv = row
        blob = json.dumps(
            {
                "mu": json.loads(mu),
                "sigma_inv": json.loads(sigma_inv),
                "calibrated_at": calibrated_at.isoformat() if hasattr(calibrated_at, "isoformat") else str(calibrated_at),
                "included_pclass_ids": json.loads(included_pclass_ids or "[]"),
                "included_years": json.loads(included_years or "[]"),
                "n_samples": n_samples,
            }
        )
        bind.execute(
            sa.text("UPDATE tenants SET ai_calibration = :blob WHERE id = :tenant_id"),
            {"blob": blob, "tenant_id": tenant_id},
        )

    op.drop_table("tenant_ai_calibrations")
