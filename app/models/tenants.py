#
# Created by David Seery on 02/03/2026.
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
from .model_mixins import ColouredLabelMixin


class Tenant(db.Model, ColouredLabelMixin):
    """
    Model an individual tenant
    """

    __tablename__ = "tenants"

    # primary key
    id = db.Column(db.Integer, primary_key=True)

    # name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH))

    # in 2026 ATAS campaign
    in_2026_ATAS_campaign = db.Column(db.Boolean, default=False)

    # AI concern calibration data — JSON blob storing the Mahalanobis calibration
    # for the (MATTR, MTLD, sentence_CV) space. Null until first calibration run.
    # Schema: {
    #   "mu": [mu_mattr, mu_mtld, mu_cv],
    #   "sigma_inv": [[...3×3 row-major pseudoinverse...]],
    #   "calibrated_at": "ISO datetime string",
    #   "included_pclass_ids": [int, ...],
    #   "included_years": [int, ...],
    #   "n_samples": int
    # }
    ai_calibration = db.Column(db.Text(), default=None)

    @property
    def ai_calibration_data(self) -> dict | None:
        """Deserialise the ai_calibration JSON blob. Returns None if not yet set."""
        if not self.ai_calibration:
            return None
        return json.loads(self.ai_calibration)

    def set_ai_calibration_data(self, data: dict) -> None:
        """Serialise and store calibration data."""
        self.ai_calibration = json.dumps(data)

    def make_label(self, text=None):
        if text is None:
            text = self.name

        return self._make_label(text)
