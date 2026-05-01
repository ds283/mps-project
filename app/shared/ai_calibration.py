#
# Created by David Seery on 13/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
AI concern calibration utilities.

This module provides:

  compute_calibration()     — fit a Mahalanobis centroid from historical
                              SubmissionRecord data for a given tenant

  mahalanobis_distance()    — evaluate sigma and chi² p-value for a new
                              observation given a TenantAICalibration object

Feature sets
------------
  "lexical"  — 3D: (MATTR, MTLD, sentence_cv)
  "full"     — 4D: (MATTR, MTLD, sentence_cv, mean_nll)
               nll_cv is stored in submission metrics for display but is not
               a Mahalanobis feature dimension.

The squared Mahalanobis distance D² = (x - μ)ᵀ Σ⁻¹ (x - μ) follows a
chi²(df) distribution under the null hypothesis that the submission was drawn
from the same pre-LLM population, where df equals the feature dimensionality.

Because MATTR and MTLD are strongly correlated the empirical covariance matrix
Σ is typically ill-conditioned.  We therefore invert it using the
Moore-Penrose pseudoinverse (numpy.linalg.pinv) with its default tolerance,
which gracefully handles near-singular directions.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import numpy as np
from scipy.stats import chi2

if TYPE_CHECKING:
    from ..models.ai_calibration import TenantAICalibration


# ---------------------------------------------------------------------------
# Minimum number of complete feature-vector rows required before we consider
# a calibration reliable.
# ---------------------------------------------------------------------------
CALIBRATION_MIN_SAMPLES = 10


def compute_calibration(
    tenant_id: int,
    pclass_ids: Optional[list[int]] = None,
    years: Optional[list[int]] = None,
    feature_set: str = "lexical",
) -> dict:
    """
    Collect feature-vector rows from completed SubmissionRecords belonging to
    *tenant_id*, optionally filtered to specific project class IDs and/or
    academic years (ProjectClassConfig.year values).

    feature_set controls which metrics are extracted:

      "lexical"  — (MATTR, MTLD, sentence_cv) triples  [default]
      "full"     — (MATTR, MTLD, sentence_cv, mean_nll) 4-tuples
                   Records missing mean_nll are skipped.

    Returns a dict::

        {
          "feature_set":         str,
          "mu":                  list[float],
          "sigma_inv":           list[list[float]],   # row-major
          "calibrated_at":       str,                 # ISO datetime
          "included_pclass_ids": list[int],
          "included_years":      list[int],
          "n_samples":           int,
        }

    Raises ValueError if fewer than CALIBRATION_MIN_SAMPLES complete rows are
    available after filtering.
    """
    # Import here to avoid circular imports at module load time.
    from ..database import db
    from ..models import ProjectClass, ProjectClassConfig, SubmissionPeriodRecord, SubmissionRecord

    # Build query joining through the tenant → pclass → config → period → record chain.
    q = (
        db.session.query(SubmissionRecord)
        .join(SubmissionPeriodRecord, SubmissionRecord.period_id == SubmissionPeriodRecord.id)
        .join(ProjectClassConfig, SubmissionPeriodRecord.config_id == ProjectClassConfig.id)
        .join(ProjectClass, ProjectClassConfig.pclass_id == ProjectClass.id)
        .filter(ProjectClass.tenant_id == tenant_id)
        .filter(SubmissionRecord.language_analysis_complete == True)  # noqa: E712
    )

    if pclass_ids:
        q = q.filter(ProjectClass.id.in_(pclass_ids))

    if years:
        q = q.filter(ProjectClassConfig.year.in_(years))

    records = q.all()

    # Extract complete feature rows, skipping records with any None value.
    rows: list[tuple] = []
    for rec in records:
        la = rec.language_analysis_data
        metrics = la.get("metrics", {})
        mattr = metrics.get("mattr")
        mtld = metrics.get("mtld")
        sentence_cv = metrics.get("sentence_cv")
        if mattr is None or mtld is None or sentence_cv is None:
            continue

        if feature_set == "full":
            mean_nll = metrics.get("mean_nll")
            if mean_nll is None:
                continue
            rows.append((float(mattr), float(mtld), float(sentence_cv), float(mean_nll)))
        else:
            rows.append((float(mattr), float(mtld), float(sentence_cv)))

    n_samples = len(rows)
    if n_samples < CALIBRATION_MIN_SAMPLES:
        raise ValueError(
            f"Only {n_samples} complete feature rows found "
            f"(minimum required: {CALIBRATION_MIN_SAMPLES}).  Broaden the "
            f"project class or year selection."
        )

    X = np.array(rows, dtype=float)  # shape (n_samples, d)

    mu = X.mean(axis=0)  # shape (d,)

    # numpy.cov expects variables in rows, observations in columns.
    Sigma = np.cov(X.T)  # shape (d, d)

    # Use Moore-Penrose pseudoinverse to handle the near-singular case that
    # arises because MATTR and MTLD are strongly correlated.
    Sigma_inv = np.linalg.pinv(Sigma)

    # Collect metadata about which project classes and years were used.
    included_pclass_ids = sorted({
        rec.period.config.pclass_id for rec in records
        if rec.period and rec.period.config
    })
    included_years = sorted({
        rec.period.config.year for rec in records
        if rec.period and rec.period.config and rec.period.config.year is not None
    })

    return {
        "feature_set": feature_set,
        "mu": mu.tolist(),
        "sigma_inv": Sigma_inv.tolist(),
        "calibrated_at": datetime.now().isoformat(),
        "included_pclass_ids": included_pclass_ids,
        "included_years": included_years,
        "n_samples": n_samples,
    }


def mahalanobis_distance(
    features: list[float],
    calibration: "TenantAICalibration",
) -> tuple[float, float]:
    """
    Compute the Mahalanobis distance sigma and chi² p-value for a feature
    vector *features* given a TenantAICalibration object.

    *features* must have length matching calibration.n_features (3 for
    "lexical", 4 for "full").

    Returns ``(sigma, p_value)`` where:

        sigma    = sqrt( (x - μ)ᵀ Σ⁻¹ (x - μ) )
        p_value  = P(chi²(df) > sigma²)  =  chi2.sf(sigma², df=n_features)

    A large sigma (small p_value) means the observation is far from the
    pre-LLM centroid, which we use as a proxy for possible AI-assisted writing.
    """
    mu = np.array(calibration.mu_data, dtype=float)
    Sigma_inv = np.array(calibration.sigma_inv_data, dtype=float)

    x = np.array(features, dtype=float)
    diff = x - mu

    D_sq = float(diff @ Sigma_inv @ diff)
    # Guard against tiny negative values from floating-point rounding.
    D_sq = max(D_sq, 0.0)

    sigma = float(np.sqrt(D_sq))
    p_value = float(chi2.sf(D_sq, df=calibration.n_features))

    return sigma, p_value
