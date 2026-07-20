#
# Created by David Seery on 01/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import json

from ..database import db
from .defaults import DEFAULT_STRING_LENGTH


class TenantAICalibration(db.Model):
    """
    One calibration object for a tenant, covering a specific combination of
    feature set and LLM configuration (or no LLM config for lexical-only 3D calibrations).
    """

    __tablename__ = "tenant_ai_calibrations"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)

    # Calibration provenance
    calibrated_at = db.Column(db.DateTime, nullable=False)
    n_samples = db.Column(db.Integer, nullable=False)
    included_years = db.Column(db.Text(collation="utf8_bin"))  # JSON list[int]
    included_pclass_ids = db.Column(db.Text(collation="utf8_bin"))  # JSON list[int]

    # LLM configuration (null for lexical-only calibrations)
    llm_model_name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"), nullable=True)
    llm_context_window = db.Column(db.Integer, nullable=True)

    # Feature space: "lexical" (3D: MATTR, MTLD, sentence_cv)
    #                "full"    (5D: + mean_nll, nll_cv)
    feature_set = db.Column(db.String(32, collation="utf8_bin"), nullable=False, default="lexical")

    # Mahalanobis parameters stored as JSON; dimensions implied by feature_set
    mu = db.Column(db.Text(collation="utf8_bin"), nullable=False)  # JSON list
    sigma_inv = db.Column(db.Text(collation="utf8_bin"), nullable=False)  # JSON row-major matrix

    tenant = db.relationship(
        "Tenant",
        backref=db.backref("ai_calibrations", cascade="all, delete-orphan"),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id",
            "feature_set",
            "llm_model_name",
            "llm_context_window",
            name="uq_tenant_calibration",
        ),
    )

    @property
    def mu_data(self) -> list:
        return json.loads(self.mu)

    @property
    def sigma_inv_data(self) -> list:
        return json.loads(self.sigma_inv)

    @property
    def n_features(self) -> int:
        return len(self.mu_data)

    @property
    def included_years_data(self) -> list:
        return json.loads(self.included_years or "[]")

    @property
    def included_pclass_ids_data(self) -> list:
        return json.loads(self.included_pclass_ids or "[]")

    def is_llm_matched(self, model_name: str | None, context_window: int | None) -> bool:
        return self.llm_model_name == model_name and self.llm_context_window == context_window

    def validate_pclass_exclusivity(self, session) -> list[int]:
        """Return pclass IDs already assigned to a sibling calibration for this tenant/feature_set/llm combo."""
        my_ids = set(json.loads(self.included_pclass_ids or "[]"))
        q = session.query(TenantAICalibration).filter_by(
            tenant_id=self.tenant_id,
            feature_set=self.feature_set,
            llm_model_name=self.llm_model_name,
            llm_context_window=self.llm_context_window,
        )
        # Only exclude self when it has been persisted; for a new (unsaved) object
        # self.id is None and there is nothing to exclude.
        if self.id is not None:
            q = q.filter(TenantAICalibration.id != self.id)
        conflicts = []
        for sibling in q.all():
            sibling_ids = set(json.loads(sibling.included_pclass_ids or "[]"))
            conflicts.extend(my_ids & sibling_ids)
        return conflicts
