"""
mahalanobis_core.py — Shared Mahalanobis-distance engine for AI-use detection.

Extracted from lexical_diversity_pipeline.py so that both the cohort-level
analysis pipeline and single-document diagnostic scripts (test_language_analysis.py)
can share the same covariance-weighted distance-from-pre-LLM-centroid implementation,
instead of the legacy literature-threshold classification in language_analysis_core.py.

Mahalanobis distance modes
--------------------------
Two modes are supported, matching lexical_diversity_pipeline.py:

  Self-built mode (default)
      Fit centroid and correlation matrix from the pre-LLM student cohort
      (PRE_LLM_YEARS) via build_reference(), then score rows with mahal_dist().
      Uses standardised z-scores: z = (x − mean) / std, σ = √(z ᵀ inv_corr z).
      σ values are NOT numerically comparable to production values because
      production uses the raw covariance inverse (see below).

  Production calibration mode
      Load mu and sigma_inv from the "Calibrations" sheet of an AI dashboard
      export workbook via load_production_calibration(), then score rows with
      mahal_dist_production(). Production fits:
      sigma_inv = pinv(cov(X.T)) in raw (non-standardised) feature space
      (see app/shared/ai_calibration.compute_calibration()). Distance:
          delta = x − mu,  σ = √(delta ᵀ sigma_inv delta)
      σ values produced in this mode are numerically identical to production
      values.

classify_mahalanobis() converts a σ value into a low/medium/high label using
the same χ² thresholds used for plot coloring in lexical_diversity_pipeline.py,
collapsed to a single calibration (K=1) — i.e. the Bonferroni correction in
app/tasks/language_analysis.py:_ai_concern_flag() with K=1.
"""

import numpy as np
import pandas as pd
from numpy.linalg import inv
from scipy import stats

# Student report dashboard Excel file
STUDENT_FILE = "AI_Dashboard_Global_2026-04-13_10-08-23.xlsx"

# Cohort definitions
PRE_LLM_YEARS = ["2019/2020", "2020/2021", "2021/2022"]
POST_LLM_YEARS = ["2023/2024", "2024/2025", "2025/2026"]
TRANS_YEARS = ["2022/2023"]
EXCLUDE_YEARS = []  # too small; add to POST_LLM_YEARS when complete


def split_cohorts(student):
    student_main = student[~student["Academic Year"].isin(EXCLUDE_YEARS)].copy()
    pre = student_main[student_main["Academic Year"].isin(PRE_LLM_YEARS)]
    post = student_main[student_main["Academic Year"].isin(POST_LLM_YEARS)]
    trans = student_main[student_main["Academic Year"].isin(TRANS_YEARS)]
    return student_main, pre, post, trans


def build_reference(pre):
    """Estimate centroid and inverse correlation matrix from pre-LLM cohort."""
    pre_3 = pre.dropna(subset=["MATTR", "MTLD", "CV"])[["MATTR", "MTLD", "CV"]]
    mean_3 = pre_3.mean().values
    std_3 = pre_3.std().values
    corr_3 = np.corrcoef(pre_3.T)
    inv_corr = inv(corr_3)
    cond_num = np.linalg.cond(corr_3)
    print(f"\nPre-LLM reference (n={len(pre_3)} complete cases):")
    print(f"  Centroid: MATTR={mean_3[0]:.6f}, MTLD={mean_3[1]:.4f}, CV={mean_3[2]:.6f}")
    print(f"  Correlation matrix condition number: {cond_num:.2f}  (well-conditioned < 100)")
    return mean_3, std_3, corr_3, inv_corr


def mahal_dist(df, mean_3, std_3, inv_corr):
    sub = df.dropna(subset=["MATTR", "MTLD", "CV"])[["MATTR", "MTLD", "CV"]]

    def _d(row):
        z = (row.values - mean_3) / std_3
        return np.sqrt(z @ inv_corr @ z)

    return sub.apply(_d, axis=1).values


def load_production_calibration(
    cal_file: str,
    cal_type: str = "lexical",
    cal_llm: str | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Load mu and sigma_inv from the Calibrations sheet of an AI dashboard export.

    The Calibrations sheet is produced by the production export task
    (app/tasks/ai_dashboard_export.export_ai_dashboard_xlsx) and contains
    the pre-computed TenantAICalibration parameters: mu (raw mean vector) and
    sigma_inv (Moore-Penrose pseudoinverse of raw covariance matrix).

    Feature ordering is validated against the feature_i label columns in the
    sheet to catch export/version mismatches before any computation.

    Returns (mu, sigma_inv) as numpy arrays for use with mahal_dist_production().
    Feature order for lexical (3-D): [MATTR, MTLD, sentence_cv]
                   for full    (5-D): [MATTR, MTLD, sentence_cv, mean_nll, nll_cv]
    Note: the student export uses the column name 'CV' for sentence_cv.
    Legacy 4-D "full" exports (produced before the 5D upgrade) are also supported;
    dimensionality is inferred from the number of non-empty feature_i label columns.
    """
    df = pd.read_excel(cal_file, sheet_name="Calibrations")

    mask = df["feature_set"] == cal_type
    if cal_llm is not None:
        mask = mask & (df["llm_model_name"] == cal_llm)

    candidates = df[mask]
    if candidates.empty:
        desc = f"feature_set={cal_type!r}"
        if cal_llm:
            desc += f", llm_model_name={cal_llm!r}"
        raise ValueError(
            f"No calibration found in {cal_file!r} matching {desc}. Available rows:\n{df[['feature_set', 'llm_model_name']].to_string()}"
        )
    if len(candidates) > 1:
        raise ValueError(
            f"Multiple calibrations match feature_set={cal_type!r} in {cal_file!r}. Use --calibration-llm to select one by LLM model name."
        )

    row = candidates.iloc[0]
    # Infer dimensionality from stored feature labels (handles legacy 4D and new 5D exports).
    if cal_type == "lexical":
        n = 3
    else:
        n = sum(1 for i in range(5) if str(row.get(f"feature_{i}", "")).strip())
        if n == 0:
            n = 4  # fallback for very old exports that lack feature_i columns
    _full_labels = ["MATTR", "MTLD", "sentence_cv", "mean_nll", "nll_cv"]
    expected_labels = ["MATTR", "MTLD", "sentence_cv"] if cal_type == "lexical" else _full_labels[:n]

    for i, exp in enumerate(expected_labels):
        got = str(row.get(f"feature_{i}", ""))
        if got != exp:
            raise ValueError(
                f"Feature label mismatch at index {i}: expected {exp!r}, got {got!r}. The export may be from an incompatible pipeline version."
            )

    mu = np.array([float(row[f"mu_{i}"]) for i in range(n)], dtype=float)
    sigma_inv = np.array(
        [[float(row[f"sigma_inv_{i}_{j}"]) for j in range(n)] for i in range(n)],
        dtype=float,
    )

    n_samples = int(row.get("n_samples", 0))
    calibrated_at = str(row.get("calibrated_at", "unknown"))
    print(f"\nProduction calibration loaded from {cal_file!r}:")
    print(f"  feature_set={cal_type!r}  n_samples={n_samples}  calibrated_at={calibrated_at}")
    print(f"  mu = {mu}")
    print(f"  sigma_inv shape = {sigma_inv.shape}")
    print(
        "\n  NOTE: σ values computed in this mode use raw feature space and are\n"
        "  numerically identical to production values.  Scatter plot display\n"
        "  coordinates still use the self-built standardised reference.\n"
    )
    return mu, sigma_inv


def mahal_dist_production(
    df: pd.DataFrame,
    mu: np.ndarray,
    sigma_inv: np.ndarray,
) -> np.ndarray:
    """Compute Mahalanobis distances using production calibration parameters.

    Mirrors app/shared/ai_calibration.mahalanobis_distance() exactly:
        delta = x − mu  (raw feature values, NOT z-scores)
        σ = sqrt(max(delta ᵀ · sigma_inv · delta, 0))

    The student export uses column 'CV' for sentence_cv (feature index 2).
    Only rows with non-null MATTR, MTLD, and CV are processed.
    """
    sub = df.dropna(subset=["MATTR", "MTLD", "CV"])[["MATTR", "MTLD", "CV"]]

    def _d(row):
        delta = row.values - mu
        D_sq = float(delta @ sigma_inv @ delta)
        return float(np.sqrt(max(D_sq, 0.0)))

    return sub.apply(_d, axis=1).values


def classify_mahalanobis(sigma: float, df: int = 3) -> tuple[float, str]:
    """Return (p_value, label) for a Mahalanobis sigma under chi2(df).

    label thresholds mirror app/tasks/language_analysis.py:_ai_concern_flag()
    collapsed to a single calibration (K=1): p<=0.01 -> "high", p<=0.05 -> "medium",
    else "low".
    """
    p_value = float(stats.chi2.sf(sigma**2, df=df))
    if p_value <= 0.01:
        label = "high"
    elif p_value <= 0.05:
        label = "medium"
    else:
        label = "low"
    return p_value, label
