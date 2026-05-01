#
# Created by David Seery on 02/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from __future__ import annotations

from typing import TYPE_CHECKING

from ..database import db
from .defaults import DEFAULT_STRING_LENGTH
from .model_mixins import ColouredLabelMixin

if TYPE_CHECKING:
    from .ai_calibration import TenantAICalibration


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

    # ai_calibrations relationship is defined via backref on TenantAICalibration

    def get_calibration(
        self,
        feature_set: str = "lexical",
        llm_model_name: str | None = None,
        llm_context_window: int | None = None,
    ) -> "TenantAICalibration | None":
        """Return the matching TenantAICalibration, or None if not yet calibrated."""
        for cal in self.ai_calibrations:
            if cal.feature_set != feature_set:
                continue
            if feature_set == "full" and not cal.is_llm_matched(llm_model_name, llm_context_window):
                continue
            return cal
        return None

    def make_label(self, text=None):
        if text is None:
            text = self.name

        return self._make_label(text)
