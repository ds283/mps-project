"""
lexical_diversity_pipeline.py — Statistical analysis and plotting pipeline
for AI-use detection in student final-year project reports.

Role in the analysis chain
--------------------------
This script is the analysis and visualisation stage, consuming outputs from
two upstream sources and producing plots and statistics:

    AI dashboard export (.xlsx)           arXiv control results (.xlsx)
        (student metrics + optional           (from arxiv_control_analysis.py;
         Calibrations sheet)                   one sheet per paper set)
               ↓                                          ↓
               └──────────────────┬───────────────────────┘
                                  ↓
                  lexical_diversity_pipeline.py  (this script)
                                  ↓  produces
                          pipeline_outputs/
                          ├── 01_violin_boxplots.png
                          ├── 02_mahal_histograms.png
                          ├── 03_mahal_kde.png
                          ├── 04a/b/c_scatter_*.png
                          ├── 05_metric_kde.png
                          └── stats_summary.txt

Mahalanobis distance modes
--------------------------
This script computes 3-D Mahalanobis σ in two modes, controlled by
--calibration-file:

  Self-built mode (default)
      Fits its own centroid and correlation matrix from the pre-LLM student
      cohort (PRE_LLM_YEARS). Uses standardised z-scores:
          z = (x − mean) / std,  σ = √(z ᵀ inv_corr z)
      σ values are NOT numerically comparable to production values because
      production uses the raw covariance inverse (see below).

  Production calibration mode (--calibration-file PATH)
      Loads mu and sigma_inv from the "Calibrations" sheet of an AI dashboard
      export workbook.  Production fits: sigma_inv = pinv(cov(X.T)) in raw
      (non-standardised) feature space (confirmed in
      app/shared/ai_calibration.compute_calibration()).  Distance computation:
          delta = x − mu,  σ = √(delta ᵀ sigma_inv delta)
      σ values produced in this mode are numerically identical to production
      values and can be directly compared with the Mahalanobis σ columns in
      the AI dashboard export.

      Scatter plot display coordinates still use the self-built standardised
      reference for axis positioning (ellipses, human-normal bands, etc.),
      even when production calibration is active for σ values.  The σ labels
      on individual outlier points reflect production values.

Usage
-----
  python lexical_diversity_pipeline.py [options]

  # Use production calibration from an AI dashboard export:
  python lexical_diversity_pipeline.py --calibration-file AI_Dashboard_...xlsx

Options
-------
  --student FILE              Student report Excel file
  --arxiv FILE                arXiv control results Excel file
  --output DIR                Output directory [default: pipeline_outputs]
  --sheets NAME,...           Comma-separated arXiv sheets to include
  --exclude-sheets NAME,...   Comma-separated arXiv sheets to exclude
  --scatter SPEC              Custom scatter plot spec (repeatable)
  --calibration-file PATH     AI dashboard export .xlsx with Calibrations sheet
  --calibration-type STR      Feature set to use: lexical or full [default: lexical]
  --calibration-llm MODEL     LLM model name to select among full calibrations

Dependencies
------------
    pandas, numpy, scipy, matplotlib, openpyxl
    Install with:  pip install pandas numpy scipy matplotlib openpyxl

Outputs (written to OUTPUT_DIR)
--------------------------------
    01_violin_boxplots.png
    02_mahal_histograms.png
    03_mahal_kde.png
    04a_scatter_students_zoom.png
    04b_scatter_students_full.png
    04c_scatter_control.png
    05_metric_kde.png
    stats_summary.txt

Author notes
------------
Pipeline developed through iterative analysis in Claude.ai (April–May 2026).
Pre-LLM reference cohort: 2019/20, 2020/21, 2021/22 (n=148 complete cases).
Post-LLM cohort: 2023/24, 2024/25 (2022/23 treated as transitional).
"""

import argparse

import matplotlib
import numpy as np
import pandas as pd
from numpy.linalg import inv
from scipy import stats

matplotlib.use("Agg")
import os
import sys
import warnings

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

warnings.filterwarnings("ignore")

# =============================================================================
# CONFIGURATION — edit this block when new data arrives
# =============================================================================

# Student report dashboard Excel file
STUDENT_FILE = "AI_Dashboard_Global_2026-04-13_10-08-23.xlsx"

# arXiv control Excel file (all sheets loaded by default)
ARXIV_FILE = "arxiv_control_results.xlsx"

# Output directory for plots and stats
OUTPUT_DIR = "pipeline_outputs"

# Cohort definitions
PRE_LLM_YEARS = ["2019/2020", "2020/2021", "2021/2022"]
POST_LLM_YEARS = ["2023/2024", "2024/2025"]
TRANS_YEARS = ["2022/2023"]
EXCLUDE_YEARS = ["2025/2026"]  # too small; add to POST_LLM_YEARS when complete

# Year display order and labels
YEAR_ORDER = [
    "2019/2020",
    "2020/2021",
    "2021/2022",
    "2022/2023",
    "2023/2024",
    "2024/2025",
]
YEAR_LABELS = ["2019/20", "2020/21", "2021/22", "2022/23", "2023/24", "2024/25"]

# Human academic normal ranges (from metric documentation)
HUMAN_NORMAL = {
    "MATTR": (0.70, 0.85),
    "MTLD": (70, 120),
    "Burstiness R": (0.20, 0.60),
    "CV": (0.55, 0.85),
}

# Power analysis: expected size of next incoming cohort
NEXT_COHORT_N = 55  # 3 existing 2025/26 + 52 incoming

# =============================================================================
# COLOURS AND STYLE
# =============================================================================

PRE_COL = "#4a6fa5"
POST_COL = "#e07b39"
TRANS_COL = "#888888"
HN_COL = "#2255aa"

# Palette for arXiv control groups — cycles if more groups than entries
_CONTROL_PALETTE = [
    "#1b7837",  # green           — djs61:     high contrast
    "#9467bd",  # purple          — byrnes_c:  keep, works fine in isolation
    "#17becf",  # cyan/teal       — burrage_c: replaces brown; max contrast vs purple
    "#e377c2",  # pink            — astro-ph.CO: keep
    "#bcbd22",  # yellow-green    — slot 5
    "#8c564b",  # brown           — slot 6 (demoted to rarely-used)
    "#ff7f0e",  # amber           — slot 7
]
_CONTROL_MARKERS = ["s", "^", "D", "P", "X", "v", "<"]


def assign_control_colors(names: list) -> dict:
    return {n: _CONTROL_PALETTE[i % len(_CONTROL_PALETTE)] for i, n in enumerate(names)}


def assign_control_markers(names: list) -> dict:
    return {n: _CONTROL_MARKERS[i % len(_CONTROL_MARKERS)] for i, n in enumerate(names)}


# =============================================================================
# CLI
# =============================================================================


def parse_args():
    p = argparse.ArgumentParser(description="Lexical diversity analysis pipeline")
    p.add_argument(
        "--student",
        default=STUDENT_FILE,
        help=f"Student report Excel file [default: {STUDENT_FILE}]",
    )
    p.add_argument(
        "--arxiv",
        default=ARXIV_FILE,
        help=f"arXiv control Excel file [default: {ARXIV_FILE}]",
    )
    p.add_argument(
        "--output", default=OUTPUT_DIR, help=f"Output directory [default: {OUTPUT_DIR}]"
    )
    grp = p.add_mutually_exclusive_group()
    grp.add_argument(
        "--sheets",
        default=None,
        help="Comma-separated arXiv sheet names to include (default: all)",
    )
    grp.add_argument(
        "--exclude-sheets",
        default=None,
        dest="exclude_sheets",
        help="Comma-separated arXiv sheet names to exclude",
    )
    p.add_argument(
        "--scatter",
        action="append",
        dest="scatter_specs",
        default=None,
        metavar="SPEC",
        help=(
            "Comma-separated list of datasets to include in an additional scatter plot. "
            "Use 'students' for pre+post cohorts; use a sheet name for a control group. "
            "Repeat to generate multiple plots, e.g. "
            "--scatter students,claude-ai --scatter students,djs61"
        ),
    )

    cal = p.add_argument_group(
        "Production calibration",
        "Load mu/sigma_inv from the Calibrations sheet of an AI dashboard export "
        "so that σ values are numerically identical to production values.",
    )
    cal.add_argument(
        "--calibration-file",
        default=None,
        metavar="PATH",
        dest="calibration_file",
        help="AI dashboard export .xlsx file containing a 'Calibrations' sheet",
    )
    cal.add_argument(
        "--calibration-type",
        default="lexical",
        choices=["lexical", "full"],
        dest="calibration_type",
        help="Feature set to use from the calibration: lexical (3-D) or full (4-D) "
             "[default: lexical]",
    )
    cal.add_argument(
        "--calibration-llm",
        default=None,
        metavar="MODEL",
        dest="calibration_llm",
        help="LLM model name used to select among multiple full calibrations",
    )

    return p.parse_args()


# =============================================================================
# LOAD DATA
# =============================================================================


def load_data(student_file, arxiv_file, include_sheets=None, exclude_sheets=None):
    """Load student and arXiv control data.

    Returns (student DataFrame, controls dict[sheet_name -> DataFrame]).
    """
    print("Loading data...")
    student = pd.read_excel(student_file, header=0)
    xf = pd.ExcelFile(arxiv_file)
    sheet_names = xf.sheet_names
    if include_sheets is not None:
        sheet_names = [s for s in sheet_names if s in include_sheets]
    elif exclude_sheets is not None:
        sheet_names = [s for s in sheet_names if s not in exclude_sheets]
    controls = {}
    for name in sheet_names:
        df = pd.read_excel(arxiv_file, sheet_name=name)
        df.rename(
            columns={
                "mattr": "MATTR",
                "mtld": "MTLD",
                "burstiness": "Burstiness R",
                "sentence_cv": "CV",
            },
            inplace=True,
        )
        controls[name] = df
        print(f"  {name}: {len(df)} records")
    print(f"  Student records: {len(student)}")
    return student, controls


def split_cohorts(student):
    student_main = student[~student["Academic Year"].isin(EXCLUDE_YEARS)].copy()
    pre = student_main[student_main["Academic Year"].isin(PRE_LLM_YEARS)]
    post = student_main[student_main["Academic Year"].isin(POST_LLM_YEARS)]
    trans = student_main[student_main["Academic Year"].isin(TRANS_YEARS)]
    return student_main, pre, post, trans


# =============================================================================
# MAHALANOBIS DISTANCE (standardised / correlation-based)
# =============================================================================


def build_reference(pre):
    """Estimate centroid and inverse correlation matrix from pre-LLM cohort."""
    pre_3 = pre.dropna(subset=["MATTR", "MTLD", "CV"])[["MATTR", "MTLD", "CV"]]
    mean_3 = pre_3.mean().values
    std_3 = pre_3.std().values
    corr_3 = np.corrcoef(pre_3.T)
    inv_corr = inv(corr_3)
    cond_num = np.linalg.cond(corr_3)
    print(f"\nPre-LLM reference (n={len(pre_3)} complete cases):")
    print(
        f"  Centroid: MATTR={mean_3[0]:.6f}, MTLD={mean_3[1]:.4f}, CV={mean_3[2]:.6f}"
    )
    print(
        f"  Correlation matrix condition number: {cond_num:.2f}  (well-conditioned < 100)"
    )
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
            f"No calibration found in {cal_file!r} matching {desc}. "
            f"Available rows:\n{df[['feature_set', 'llm_model_name']].to_string()}"
        )
    if len(candidates) > 1:
        raise ValueError(
            f"Multiple calibrations match feature_set={cal_type!r} in {cal_file!r}. "
            "Use --calibration-llm to select one by LLM model name."
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
                f"Feature label mismatch at index {i}: expected {exp!r}, got {got!r}. "
                "The export may be from an incompatible pipeline version."
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


def display_coords(df, mean_3, std_3, inv_corr):
    """Return (x_combined, y_cv, mahalanobis) for scatter plots."""
    sub = df.dropna(subset=["MATTR", "MTLD", "CV"])[["MATTR", "MTLD", "CV"]].copy()
    x = (
        (sub["MATTR"] - mean_3[0]) / std_3[0] + (sub["MTLD"] - mean_3[1]) / std_3[1]
    ) / np.sqrt(2)
    y = (sub["CV"] - mean_3[2]) / std_3[2]
    mah = sub.apply(
        lambda r: np.sqrt(
            ((r.values - mean_3) / std_3) @ inv_corr @ ((r.values - mean_3) / std_3)
        ),
        axis=1,
    ).values
    return x.values, y.values, mah


def build_ellipses(corr_3, thresh_05, thresh_01):
    """Build 2D confidence ellipses for the (MATTR+MTLD, CV) display space."""
    T = np.array([[1 / np.sqrt(2), 1 / np.sqrt(2), 0], [0, 0, 1]])
    Sigma_2d = T @ corr_3 @ T.T
    eigvals_2d, eigvecs_2d = np.linalg.eigh(Sigma_2d)
    eigvals_2d = eigvals_2d[::-1]
    eigvecs_2d = eigvecs_2d[:, ::-1]

    def _ellipse(thresh):
        thresh_2d = np.sqrt(stats.chi2.ppf(stats.chi2.cdf(thresh**2, df=3), df=2))
        a = np.sqrt(eigvals_2d[0]) * thresh_2d
        b = np.sqrt(eigvals_2d[1]) * thresh_2d
        angle = np.arctan2(eigvecs_2d[1, 0], eigvecs_2d[0, 0])
        theta = np.linspace(0, 2 * np.pi, 500)
        c, s = np.cos(angle), np.sin(angle)
        xe, ye = a * np.cos(theta), b * np.sin(theta)
        return c * xe - s * ye, s * xe + c * ye

    return _ellipse(thresh_05), _ellipse(thresh_01)


# =============================================================================
# PLOT 1: VIOLIN + BOX + STRIP PLOTS
# =============================================================================


def plot_violin_box(student_main, output_dir):
    metrics = ["MATTR", "MTLD", "Burstiness R", "CV"]
    metric_labels = ["MATTR", "MTLD", "Burstiness B", "Sentence CV"]

    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    fig.patch.set_facecolor("#fafafa")
    axes = axes.flatten()

    for ax, m, ml in zip(axes, metrics, metric_labels):
        ax.set_facecolor("#f7f7f7")
        lo, hi = HUMAN_NORMAL[m]
        ax.axhspan(lo, hi, alpha=0.10, color="green", zorder=0)
        ax.axhline(lo, color="green", lw=0.8, ls="--", alpha=0.5)
        ax.axhline(hi, color="green", lw=0.8, ls="--", alpha=0.5)
        ax.axvline(2.5, color="#e74c3c", lw=1.5, ls=":", alpha=0.7)

        data_by_year = [
            student_main[student_main["Academic Year"] == yr][m].dropna().values
            for yr in YEAR_ORDER
        ]
        colors_v = [
            PRE_COL
            if yr in PRE_LLM_YEARS
            else (TRANS_COL if yr in TRANS_YEARS else POST_COL)
            for yr in YEAR_ORDER
        ]

        parts = ax.violinplot(
            data_by_year,
            positions=range(len(YEAR_ORDER)),
            showmedians=True,
            showextrema=False,
        )
        for pc, col in zip(parts["bodies"], colors_v):
            pc.set_facecolor(col)
            pc.set_alpha(0.45)
            pc.set_edgecolor("grey")
            pc.set_linewidth(0.5)
        parts["cmedians"].set_color("#222222")
        parts["cmedians"].set_linewidth(1.8)

        bp = ax.boxplot(
            data_by_year,
            positions=range(len(YEAR_ORDER)),
            widths=0.18,
            patch_artist=True,
            showfliers=False,
            medianprops=dict(color="#222222", linewidth=0),
            whiskerprops=dict(linewidth=0.8, color="#555555"),
            capprops=dict(linewidth=0.8, color="#555555"),
            boxprops=dict(linewidth=0.8),
        )
        for patch, col in zip(bp["boxes"], colors_v):
            patch.set_facecolor(col)
            patch.set_alpha(0.75)

        for j, (yr, col) in enumerate(zip(YEAR_ORDER, colors_v)):
            vals = student_main[student_main["Academic Year"] == yr][m].dropna().values
            jitter = np.random.RandomState(42 + j).uniform(-0.12, 0.12, len(vals))
            ax.scatter(
                j + jitter, vals, color=col, alpha=0.30, s=10, zorder=3, linewidths=0
            )

        ax.set_xticks(range(len(YEAR_ORDER)))
        ax.set_xticklabels(YEAR_LABELS, fontsize=8.5)
        ax.set_title(ml, fontsize=11, fontweight="bold", pad=4)
        ax.tick_params(axis="y", labelsize=8)
        ax.spines[["top", "right"]].set_visible(False)

    legend_els = [
        mpatches.Patch(facecolor=PRE_COL, alpha=0.7, label="Pre-LLM"),
        mpatches.Patch(facecolor=TRANS_COL, alpha=0.7, label="Transitional (2022/23)"),
        mpatches.Patch(facecolor=POST_COL, alpha=0.7, label="Post-LLM"),
        mpatches.Patch(
            facecolor="green", alpha=0.2, label="Human academic normal range"
        ),
    ]
    fig.legend(
        handles=legend_els,
        loc="lower center",
        ncol=4,
        fontsize=9,
        bbox_to_anchor=(0.5, -0.02),
        framealpha=0.95,
        edgecolor="#cccccc",
    )
    fig.suptitle(
        "Lexical Diversity Metrics by Academic Year",
        fontsize=13,
        fontweight="bold",
        color="#1a1a2e",
    )
    plt.tight_layout(rect=[0, 0.04, 1, 0.97])
    path = os.path.join(output_dir, "01_violin_boxplots.png")
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="#fafafa")
    plt.close()
    print(f"  Saved: {path}")


# =============================================================================
# PLOT 2: MAHALANOBIS HISTOGRAMS PER YEAR
# =============================================================================


def plot_mahal_histograms(
    student_main, mahal_fn, thresh_05, thresh_01, output_dir
):
    """Plot per-year Mahalanobis distance histograms.

    *mahal_fn* is a callable (df) → np.ndarray of σ values; it is either the
    self-built mahal_dist() closure or mahal_dist_production() closure,
    depending on whether --calibration-file was supplied.
    """
    all_vals = [
        mahal_fn(student_main[student_main["Academic Year"] == yr])
        for yr in YEAR_ORDER
    ]
    global_max = max(v.max() for v in all_vals)
    x_max = global_max * 1.08
    x_ref = np.linspace(0, x_max, 400)
    chi_pdf = stats.chi.pdf(x_ref, df=3)

    fig, axes = plt.subplots(2, 3, figsize=(15, 9))
    fig.patch.set_facecolor("#fafafa")
    axes = axes.flatten()

    for i, (yr, lbl, vals) in enumerate(zip(YEAR_ORDER, YEAR_LABELS, all_vals)):
        ax = axes[i]
        ax.set_facecolor("#f7f7f7")
        col = (
            PRE_COL
            if yr in PRE_LLM_YEARS
            else (TRANS_COL if yr in TRANS_YEARS else POST_COL)
        )
        era = (
            "Pre-LLM"
            if yr in PRE_LLM_YEARS
            else ("Transitional" if yr in TRANS_YEARS else "Post-LLM")
        )

        ax.plot(x_ref, chi_pdf * len(vals) * 0.45, color="#aaaaaa", lw=1.2, ls="--")
        bins = np.linspace(0, x_max, 26)
        n, edges, patches = ax.hist(
            vals,
            bins=bins,
            color=col,
            alpha=0.60,
            edgecolor="white",
            linewidth=0.5,
            zorder=2,
        )
        for patch, left in zip(patches, edges[:-1]):
            if left >= thresh_01:
                patch.set_facecolor("#7f0000")
                patch.set_alpha(0.85)
            elif left >= thresh_05:
                patch.set_facecolor("#c0392b")
                patch.set_alpha(0.75)

        ax.axvline(thresh_05, color="#c0392b", lw=1.5, ls=":", zorder=4)
        ax.axvline(thresh_01, color="#7f0000", lw=1.2, ls=":", zorder=4)
        ax.axvline(np.mean(vals), color=col, lw=2.0, ls="-", zorder=5, alpha=0.9)
        ax.axvline(np.median(vals), color=col, lw=1.5, ls="--", zorder=5, alpha=0.7)

        n05 = (vals > thresh_05).sum()
        pct05 = 100 * n05 / len(vals)
        n01 = (vals > thresh_01).sum()
        pct01 = 100 * n01 / len(vals)
        ax.text(
            0.97,
            0.97,
            f"n={len(vals)}\nmean={np.mean(vals):.2f}\n"
            f"median={np.median(vals):.2f}\n"
            f">p0.05: {n05} ({pct05:.0f}%)\n>p0.01: {n01} ({pct01:.0f}%)",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=8.0,
            family="monospace",
            bbox=dict(
                boxstyle="round,pad=0.3",
                facecolor="white",
                alpha=0.85,
                edgecolor="#ccc",
            ),
        )
        ax.set_title(f"{lbl}  [{era}]", fontsize=10, fontweight="bold", color=col)
        ax.set_xlabel("Mahalanobis distance from pre-LLM centroid", fontsize=8)
        ax.set_ylabel("Count", fontsize=8)
        ax.set_xlim(0, x_max)
        ax.tick_params(labelsize=8)
        ax.spines[["top", "right"]].set_visible(False)

    legend_els = [
        mpatches.Patch(facecolor=PRE_COL, alpha=0.7, label="Pre-LLM cohort"),
        mpatches.Patch(facecolor=TRANS_COL, alpha=0.7, label="Transitional (2022/23)"),
        mpatches.Patch(facecolor=POST_COL, alpha=0.7, label="Post-LLM cohort"),
        mpatches.Patch(facecolor="#c0392b", alpha=0.75, label="p=0.05 to p=0.01"),
        mpatches.Patch(facecolor="#7f0000", alpha=0.85, label="Beyond p=0.01"),
        Line2D([0], [0], color="grey", lw=2.0, ls="-", label="Cohort mean"),
        Line2D([0], [0], color="grey", lw=1.5, ls="--", label="Cohort median"),
        Line2D([0], [0], color="#aaaaaa", lw=1.2, ls="--", label="χ(3) null reference"),
    ]
    fig.legend(
        handles=legend_els,
        loc="lower center",
        ncol=4,
        fontsize=8.5,
        bbox_to_anchor=(0.5, -0.04),
        framealpha=0.95,
        edgecolor="#cccccc",
    )
    fig.suptitle(
        f"Mahalanobis Distance Distributions by Academic Year\n"
        f"Reference: pre-LLM centroid;  "
        f"p=0.05→{thresh_05:.2f}σ,  p=0.01→{thresh_01:.2f}σ  "
        f"(x-axis to {x_max:.1f}σ)",
        fontsize=11,
        fontweight="bold",
        color="#1a1a2e",
    )
    plt.tight_layout(rect=[0, 0.06, 1, 0.95])
    path = os.path.join(output_dir, "02_mahal_histograms.png")
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="#fafafa")
    plt.close()
    print(f"  Saved: {path}")


# =============================================================================
# PLOT 3: KDE OF MAHALANOBIS DISTANCES
# =============================================================================


def plot_mahal_kde(
    m_pre, m_post, controls_mahal, colors, thresh_05, thresh_01, output_dir
):
    datasets_kd = {
        "Pre-LLM students": (m_pre, PRE_COL, "solid", 2.2),
        "Post-LLM students": (m_post, POST_COL, "solid", 2.2),
    }
    for name, vals in controls_mahal.items():
        datasets_kd[name] = (vals, colors[name], "dashed", 2.0)
    x_ref = np.linspace(0, 10, 400)
    chi_pdf = stats.chi.pdf(x_ref, df=3)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    fig.patch.set_facecolor("#fafafa")

    for ax, (xlim, title) in zip(
        axes,
        [
            ((0, 8), "KDE of Mahalanobis distances"),
            ((0, 14), "Extended range (arXiv scale)"),
        ],
    ):
        ax.set_facecolor("#f7f7f7")
        ax.plot(x_ref, chi_pdf * 0.5, color="#aaaaaa", lw=1.2, ls=":")
        ax.axvline(thresh_05, color="#c0392b", lw=1.5, ls="--", alpha=0.8)
        ax.axvline(thresh_01, color="#7f0000", lw=1.2, ls="--", alpha=0.7)
        for label, (vals, col, ls, lw) in datasets_kd.items():
            kde_x = np.linspace(0, xlim[1], 400)
            kde = stats.gaussian_kde(vals, bw_method=0.35)
            ax.plot(kde_x, kde(kde_x), color=col, lw=lw, ls=ls, alpha=0.85, label=label)
            ax.axvline(np.mean(vals), color=col, lw=0.9, ls=":", alpha=0.55)
        rows = [
            f"{lb[:28]:<28}  mean={v.mean():.2f}  >p05={100 * (v > thresh_05).mean():.0f}%"
            for lb, (v, *_) in datasets_kd.items()
        ]
        ax.text(
            0.97,
            0.97,
            "\n".join(rows),
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=7.0,
            family="monospace",
            bbox=dict(
                boxstyle="round,pad=0.35",
                facecolor="white",
                alpha=0.85,
                edgecolor="#ccc",
            ),
        )
        ax.set_xlim(xlim)
        ax.set_ylim(bottom=0)
        ax.set_xlabel("Mahalanobis distance from pre-LLM centroid", fontsize=9)
        ax.set_ylabel("Density", fontsize=9)
        ax.set_title(title, fontsize=10, fontweight="bold")
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(labelsize=8)

    legend_els = [
        Line2D([0], [0], color=PRE_COL, lw=2.2, ls="solid", label="Pre-LLM students"),
        Line2D([0], [0], color=POST_COL, lw=2.2, ls="solid", label="Post-LLM students"),
    ]
    for name in controls_mahal:
        legend_els.append(
            Line2D([0], [0], color=colors[name], lw=2.0, ls="dashed", label=name)
        )
    legend_els += [
        Line2D([0], [0], color="#aaaaaa", lw=1.2, ls=":", label="χ(3) null reference"),
        Line2D(
            [0],
            [0],
            color="#c0392b",
            lw=1.5,
            ls="--",
            label=f"p=0.05 ({thresh_05:.2f}σ)",
        ),
    ]
    fig.legend(
        handles=legend_els,
        loc="lower center",
        ncol=3,
        fontsize=9,
        bbox_to_anchor=(0.5, -0.10),
        framealpha=0.95,
        edgecolor="#cccccc",
    )
    fig.suptitle(
        "Mahalanobis Distance KDE", fontsize=12, fontweight="bold", color="#1a1a2e"
    )
    plt.tight_layout(rect=[0, 0.08, 1, 0.96])
    path = os.path.join(output_dir, "03_mahal_kde.png")
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="#fafafa")
    plt.close()
    print(f"  Saved: {path}")


# =============================================================================
# SCATTER PLOT HELPER FUNCTIONS
# =============================================================================


def _draw_scatter_base(
    ax,
    xlim,
    ylim,
    e05,
    e01,
    x_norm_lo,
    x_norm_hi,
    z_cv_lo,
    z_cv_hi,
    thresh_05,
    thresh_01,
):
    ax.set_facecolor("#f7f7f7")
    # Human-normal bands first (lowest zorder)
    ax.axvspan(x_norm_lo, x_norm_hi, alpha=0.13, color=HN_COL, zorder=1)
    ax.axhspan(z_cv_lo, z_cv_hi, alpha=0.13, color=HN_COL, zorder=1)
    # Confidence regions — no fill beyond p=0.01
    ax.fill(e01[0], e01[1], color="#fef0cd", zorder=2)
    ax.fill(e05[0], e05[1], color="#eef5ee", zorder=3)
    ax.plot(e05[0], e05[1], color="#c0392b", lw=1.8, ls="--", zorder=5)
    ax.plot(e01[0], e01[1], color="#7f0000", lw=1.5, ls="--", zorder=5)
    ax.axhline(0, color="#aaaaaa", lw=0.7, ls=":", zorder=4)
    ax.axvline(0, color="#aaaaaa", lw=0.7, ls=":", zorder=4)
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.set_xlabel(
        "Standardised (MATTR+MTLD)/√2\n← lower diversity          higher diversity →",
        fontsize=8.5,
    )
    ax.set_ylabel("Standardised CV\n← uniform          variable →", fontsize=8.5)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=8)


def _plot_scatter_points(
    ax, df, col, mk, al, sz, label, mean_3, std_3, inv_corr, thresh_05, thresh_01
):
    x, y, mah = display_coords(df, mean_3, std_3, inv_corr)
    b01 = mah > thresh_01
    b05 = (mah > thresh_05) & ~b01
    ins = mah <= thresh_05
    ax.scatter(
        x[ins],
        y[ins],
        c=col,
        marker=mk,
        s=sz,
        alpha=al,
        zorder=6,
        linewidths=0.3,
        edgecolors="white",
        label=label,
    )
    ax.scatter(
        x[b05],
        y[b05],
        c=col,
        marker=mk,
        s=sz * 2.0,
        alpha=0.9,
        zorder=7,
        linewidths=1.0,
        edgecolors="#c0392b",
    )
    ax.scatter(
        x[b01],
        y[b01],
        c=col,
        marker=mk,
        s=sz * 2.5,
        alpha=1.0,
        zorder=8,
        linewidths=1.4,
        edgecolors="#7f0000",
    )
    for xi, yi, mi in zip(x, y, mah):
        if mi > thresh_01:
            ax.annotate(
                f"{mi:.1f}σ",
                (xi, yi),
                textcoords="offset points",
                xytext=(6, 4),
                fontsize=7.5,
                color="#7f0000",
                fontweight="bold",
                zorder=9,
            )


def _scatter_legend(controls, colors, markers):
    els = [
        mpatches.Patch(color="#eef5ee", label="Inside p=0.05"),
        mpatches.Patch(color="#fef0cd", label="p=0.05 to p=0.01"),
        Line2D([0], [0], color="#c0392b", lw=1.8, ls="--", label="p=0.05 contour"),
        Line2D([0], [0], color="#7f0000", lw=1.5, ls="--", label="p=0.01 contour"),
        mpatches.Patch(color=PRE_COL, alpha=0.7, label="Pre-LLM students"),
        mpatches.Patch(color=POST_COL, alpha=0.7, label="Post-LLM students"),
    ]
    for name in controls:
        els.append(
            Line2D(
                [0],
                [0],
                marker=markers[name],
                color=colors[name],
                linestyle="None",
                markersize=7,
                alpha=0.8,
                label=name,
            )
        )
    els += [
        mpatches.Patch(color=HN_COL, alpha=0.25, label="Human academic normal range"),
        Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor="grey",
            markersize=8,
            markeredgecolor="#7f0000",
            markeredgewidth=1.4,
            label="Beyond p=0.01 (σ labelled)",
        ),
    ]
    return els


# =============================================================================
# PLOTS 4a, 4b, 4c: SCATTER PLOTS
# =============================================================================


def plot_scatters(
    pre,
    post,
    controls,
    colors,
    markers,
    mean_3,
    std_3,
    corr_3,
    inv_corr,
    thresh_05,
    thresh_01,
    output_dir,
):
    e05, e01 = build_ellipses(corr_3, thresh_05, thresh_01)

    # Human-normal bands in display coordinates
    x_norm_lo = ((0.70 - mean_3[0]) / std_3[0] + (70 - mean_3[1]) / std_3[1]) / np.sqrt(
        2
    )
    x_norm_hi = (
        (0.85 - mean_3[0]) / std_3[0] + (120 - mean_3[1]) / std_3[1]
    ) / np.sqrt(2)
    z_cv_lo = (0.55 - mean_3[2]) / std_3[2]
    z_cv_hi = (0.85 - mean_3[2]) / std_3[2]

    # Compute axis limits
    all_student = pd.concat([pre, post])
    xs, ys, _ = display_coords(all_student, mean_3, std_3, inv_corr)
    pad = 0.6

    xlim_zoom = (-4.5, 4.5)
    ylim_zoom = (-2.5, 4.5)
    xlim_full = (xs.min() - pad, xs.max() + pad)
    ylim_full = (ys.min() - pad, ys.max() + pad)

    x_ctrl_all, y_ctrl_all = [], []
    for df in controls.values():
        xc, yc, _ = display_coords(df, mean_3, std_3, inv_corr)
        x_ctrl_all.append(xc)
        y_ctrl_all.append(yc)
    if x_ctrl_all:
        xc_cat = np.concatenate(x_ctrl_all)
        yc_cat = np.concatenate(y_ctrl_all)
        xlim_ctrl = (xc_cat.min() - pad, xc_cat.max() + pad)
        ylim_ctrl = (yc_cat.min() - pad, yc_cat.max() + pad)
    else:
        xlim_ctrl = xlim_full
        ylim_ctrl = ylim_full

    n_pre = len(pre.dropna(subset=["MATTR", "MTLD", "CV"]))
    n_post = len(post.dropna(subset=["MATTR", "MTLD", "CV"]))
    base_kw = dict(
        mean_3=mean_3,
        std_3=std_3,
        inv_corr=inv_corr,
        thresh_05=thresh_05,
        thresh_01=thresh_01,
    )
    ell_kw = dict(
        e05=e05,
        e01=e01,
        x_norm_lo=x_norm_lo,
        x_norm_hi=x_norm_hi,
        z_cv_lo=z_cv_lo,
        z_cv_hi=z_cv_hi,
        thresh_05=thresh_05,
        thresh_01=thresh_01,
    )
    leg = _scatter_legend(controls, colors, markers)
    # Student-only legend: strip the per-control marker entries from the middle.
    # Structure: [4 region/contour patches] [2 student patches] [N control markers] [2 tail entries]
    n_fixed_top = 6  # region patches (4) + student patches (2)
    leg_no_controls = leg[:n_fixed_top] + leg[n_fixed_top + len(controls):]
    # Control-only legend: keep region/contour patches and tail, drop student patches.
    leg_ctrl_only = leg[:4] + leg[n_fixed_top:]

    def _hn_labels(ax, xlim, ylim):
        ax.text(
            x_norm_lo + 0.1,
            ylim[1] - 0.25,
            "human-normal\nMATTR+MTLD",
            fontsize=7.5,
            color=HN_COL,
            style="italic",
            va="top",
            zorder=10,
        )
        ax.text(
            xlim[0] + 0.15,
            z_cv_lo + 0.12,
            "human-normal CV",
            fontsize=7.5,
            color=HN_COL,
            style="italic",
            zorder=10,
        )

    # 4a: students zoomed
    fig, ax = plt.subplots(figsize=(9, 8))
    fig.patch.set_facecolor("#fafafa")
    _draw_scatter_base(ax, xlim_zoom, ylim_zoom, **ell_kw)
    _plot_scatter_points(
        ax, pre, PRE_COL, "o", 0.50, 30, f"Pre-LLM students (n={n_pre})", **base_kw
    )
    _plot_scatter_points(
        ax, post, POST_COL, "o", 0.75, 36, f"Post-LLM students (n={n_post})", **base_kw
    )
    _hn_labels(ax, xlim_zoom, ylim_zoom)
    ax.set_title("Student cohorts — central region", fontsize=10, fontweight="bold")
    fig.legend(
        handles=leg_no_controls,
        loc="lower center",
        ncol=4,
        fontsize=8.5,
        bbox_to_anchor=(0.5, -0.08),
        framealpha=0.95,
        edgecolor="#cccccc",
    )
    plt.tight_layout(rect=[0, 0.09, 1, 1])
    path = os.path.join(output_dir, "04a_scatter_students_zoom.png")
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="#fafafa")
    plt.close()
    print(f"  Saved: {path}")

    # 4b: students full extent
    fig, ax = plt.subplots(figsize=(10, 9))
    fig.patch.set_facecolor("#fafafa")
    _draw_scatter_base(ax, xlim_full, ylim_full, **ell_kw)
    _plot_scatter_points(
        ax, pre, PRE_COL, "o", 0.50, 30, f"Pre-LLM students (n={n_pre})", **base_kw
    )
    _plot_scatter_points(
        ax, post, POST_COL, "o", 0.75, 36, f"Post-LLM students (n={n_post})", **base_kw
    )
    _hn_labels(ax, xlim_full, ylim_full)
    ax.set_title(
        "Student cohorts — all outliers included", fontsize=10, fontweight="bold"
    )
    fig.legend(
        handles=leg_no_controls,
        loc="lower center",
        ncol=4,
        fontsize=8.5,
        bbox_to_anchor=(0.5, -0.08),
        framealpha=0.95,
        edgecolor="#cccccc",
    )
    plt.tight_layout(rect=[0, 0.09, 1, 1])
    path = os.path.join(output_dir, "04b_scatter_students_full.png")
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="#fafafa")
    plt.close()
    print(f"  Saved: {path}")

    # 4c: control samples only, axes fitted to control extent
    fig, ax = plt.subplots(figsize=(11, 9))
    fig.patch.set_facecolor("#fafafa")
    _draw_scatter_base(ax, xlim_ctrl, ylim_ctrl, **ell_kw)
    for name, df in controls.items():
        _plot_scatter_points(
            ax, df, colors[name], markers[name], 0.65, 32, name, **base_kw
        )
    _hn_labels(ax, xlim_ctrl, ylim_ctrl)
    ax.set_title(
        "arXiv control samples — Mahalanobis contours from pre-LLM reference",
        fontsize=10,
        fontweight="bold",
    )
    fig.legend(
        handles=leg_ctrl_only,
        loc="lower center",
        ncol=4,
        fontsize=8.5,
        bbox_to_anchor=(0.5, -0.10),
        framealpha=0.95,
        edgecolor="#cccccc",
    )
    plt.tight_layout(rect=[0, 0.11, 1, 1])
    path = os.path.join(output_dir, "04c_scatter_control.png")
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="#fafafa")
    plt.close()
    print(f"  Saved: {path}")


# =============================================================================
# PLOT 4d+: CUSTOM SCATTER (user-specified dataset combinations)
# =============================================================================


def plot_custom_scatter(
    spec_str,
    pre,
    post,
    controls,
    colors,
    markers,
    mean_3,
    std_3,
    corr_3,
    inv_corr,
    thresh_05,
    thresh_01,
    output_dir,
    plot_letter,
):
    """Generate a scatter plot for an arbitrary combination of datasets.

    spec_str: comma-separated tokens — 'students' for both cohorts,
              or a control sheet name for that dataset.
    plot_letter: single character appended after '04' in the filename (e.g. 'd').
    """
    tokens = [t.strip() for t in spec_str.split(",") if t.strip()]
    include_students = "students" in tokens
    control_tokens = [t for t in tokens if t != "students"]

    included_controls = {}
    for name in control_tokens:
        if name in controls:
            included_controls[name] = controls[name]
        else:
            print(f"  WARNING: --scatter token '{name}' not found in loaded sheets; skipping")

    if not include_students and not included_controls:
        print(f"  WARNING: --scatter '{spec_str}' resolved to no valid datasets; skipping")
        return

    e05, e01 = build_ellipses(corr_3, thresh_05, thresh_01)

    x_norm_lo = ((0.70 - mean_3[0]) / std_3[0] + (70 - mean_3[1]) / std_3[1]) / np.sqrt(2)
    x_norm_hi = ((0.85 - mean_3[0]) / std_3[0] + (120 - mean_3[1]) / std_3[1]) / np.sqrt(2)
    z_cv_lo = (0.55 - mean_3[2]) / std_3[2]
    z_cv_hi = (0.85 - mean_3[2]) / std_3[2]

    base_kw = dict(
        mean_3=mean_3, std_3=std_3, inv_corr=inv_corr,
        thresh_05=thresh_05, thresh_01=thresh_01,
    )
    ell_kw = dict(
        e05=e05, e01=e01,
        x_norm_lo=x_norm_lo, x_norm_hi=x_norm_hi,
        z_cv_lo=z_cv_lo, z_cv_hi=z_cv_hi,
        thresh_05=thresh_05, thresh_01=thresh_01,
    )

    # Gather all x/y values to determine axis limits
    all_x, all_y = [], []
    pad = 0.6
    if include_students:
        all_students = pd.concat([pre, post])
        xs, ys, _ = display_coords(all_students, mean_3, std_3, inv_corr)
        all_x.append(xs); all_y.append(ys)
    for df in included_controls.values():
        xc, yc, _ = display_coords(df, mean_3, std_3, inv_corr)
        all_x.append(xc); all_y.append(yc)
    all_x = np.concatenate(all_x)
    all_y = np.concatenate(all_y)
    xlim = (all_x.min() - pad, all_x.max() + pad)
    ylim = (all_y.min() - pad, all_y.max() + pad)

    fig, ax = plt.subplots(figsize=(10, 9))
    fig.patch.set_facecolor("#fafafa")
    _draw_scatter_base(ax, xlim, ylim, **ell_kw)

    if include_students:
        n_pre = len(pre.dropna(subset=["MATTR", "MTLD", "CV"]))
        n_post = len(post.dropna(subset=["MATTR", "MTLD", "CV"]))
        _plot_scatter_points(ax, pre, PRE_COL, "o", 0.50, 30, f"Pre-LLM students (n={n_pre})", **base_kw)
        _plot_scatter_points(ax, post, POST_COL, "o", 0.75, 36, f"Post-LLM students (n={n_post})", **base_kw)

    for name, df in included_controls.items():
        _plot_scatter_points(ax, df, colors[name], markers[name], 0.65, 32, name, **base_kw)

    ax.text(
        x_norm_lo + 0.1, ylim[1] - 0.25,
        "human-normal\nMATTR+MTLD", fontsize=7.5, color=HN_COL,
        style="italic", va="top", zorder=10,
    )
    ax.text(
        xlim[0] + 0.15, z_cv_lo + 0.12,
        "human-normal CV", fontsize=7.5, color=HN_COL, style="italic", zorder=10,
    )

    ax.set_title(f"Custom scatter: {', '.join(tokens)}", fontsize=10, fontweight="bold")

    leg = _scatter_legend(included_controls, colors, markers)
    n_fixed_top = 6
    if not include_students:
        leg = leg[:4] + leg[n_fixed_top:]

    fig.legend(
        handles=leg, loc="lower center", ncol=4, fontsize=8.5,
        bbox_to_anchor=(0.5, -0.08), framealpha=0.95, edgecolor="#cccccc",
    )
    plt.tight_layout(rect=[0, 0.09, 1, 1])

    slug = spec_str.replace(" ", "_").replace(",", "+")
    path = os.path.join(output_dir, f"04{plot_letter}_scatter_{slug}.png")
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="#fafafa")
    plt.close()
    print(f"  Saved: {path}")


# =============================================================================
# PLOT 5: METRIC KDE
# =============================================================================


def plot_metric_kde(pre, post, controls, colors, output_dir):
    datasets = {
        "Pre-LLM students (2019–2022)": (pre, PRE_COL, "solid", 2.2),
        "Post-LLM students (2023–2025)": (post, POST_COL, "solid", 2.2),
    }
    for name, df in controls.items():
        datasets[name] = (df, colors[name], "dashed", 2.0)
    metrics = ["MATTR", "MTLD", "Burstiness R", "CV"]
    metric_labels = ["MATTR", "MTLD", "Burstiness B", "Sentence CV"]
    xlims = {
        "MATTR": (0.48, 0.82),
        "MTLD": (20, 135),
        "Burstiness R": (-0.35, 0.55),
        "CV": (0.30, 1.80),
    }

    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    fig.patch.set_facecolor("#fafafa")
    axes = axes.flatten()

    for ax, m, ml in zip(axes, metrics, metric_labels):
        ax.set_facecolor("#f7f7f7")
        lo, hi = HUMAN_NORMAL[m]
        ax.axvspan(lo, hi, alpha=0.10, color="green", zorder=0)
        ax.axvline(lo, color="green", lw=0.8, ls="--", alpha=0.5)
        ax.axvline(hi, color="green", lw=0.8, ls="--", alpha=0.5)
        kde_x = np.linspace(*xlims[m], 400)
        for label, (df, col, ls, lw) in datasets.items():
            vals = df[m].dropna().values
            if len(vals) < 5:
                continue
            kde = stats.gaussian_kde(vals, bw_method=0.4)
            ax.plot(
                kde_x,
                kde(kde_x),
                color=col,
                lw=lw,
                ls=ls,
                alpha=0.85,
                label=f"{label}  (n={len(vals)})",
            )
            ax.axvline(vals.mean(), color=col, lw=0.9, ls=":", alpha=0.6)
        ax.set_xlim(xlims[m])
        ax.set_ylim(bottom=0)
        ax.set_xlabel(ml, fontsize=10)
        ax.set_ylabel("Density", fontsize=9)
        ax.set_title(ml, fontsize=12, fontweight="bold", pad=5)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(labelsize=8.5)
        ymax = ax.get_ylim()[1]
        ax.text(
            (lo + hi) / 2,
            ymax * 0.92,
            "human\nnormal",
            ha="center",
            va="top",
            fontsize=7.5,
            color="green",
            alpha=0.7,
            style="italic",
        )

    legend_els = [
        Line2D([0], [0], color=PRE_COL, lw=2.2, ls="solid", label="Pre-LLM students"),
        Line2D([0], [0], color=POST_COL, lw=2.2, ls="solid", label="Post-LLM students"),
    ]
    for name in controls:
        legend_els.append(
            Line2D([0], [0], color=colors[name], lw=2.0, ls="dashed", label=name)
        )
    legend_els += [
        mpatches.Patch(
            facecolor="green", alpha=0.2, label="Human academic normal range"
        ),
        Line2D([0], [0], color="grey", lw=0.9, ls=":", label="Dataset mean"),
    ]
    fig.legend(
        handles=legend_els,
        loc="lower center",
        ncol=3,
        fontsize=9.5,
        bbox_to_anchor=(0.5, -0.03),
        framealpha=0.95,
        edgecolor="#cccccc",
    )
    fig.suptitle(
        "KDE of Individual Metric Distributions",
        fontsize=13,
        fontweight="bold",
        color="#1a1a2e",
    )
    plt.tight_layout(rect=[0, 0.05, 1, 0.97])
    path = os.path.join(output_dir, "05_metric_kde.png")
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="#fafafa")
    plt.close()
    print(f"  Saved: {path}")


# =============================================================================
# STATISTICAL TESTS
# =============================================================================


def run_stats(
    pre,
    post,
    controls,
    controls_mahal,
    student_main,
    mahal_fn,
    thresh_05,
    thresh_01,
    output_dir,
):
    """Run statistical tests and write stats_summary.txt.

    *mahal_fn* is a callable (df) → np.ndarray of σ values, consistent with
    the mode used to compute controls_mahal (self-built or production).
    """
    lines = []

    def p(s):
        lines.append(s)
        print(s)

    m_pre = mahal_fn(pre)
    m_post = mahal_fn(post)

    p("=" * 72)
    p("STATISTICAL TESTS ON MAHALANOBIS DISTANCE DISTRIBUTIONS")
    p("=" * 72)

    p("\n--- Pairwise comparisons (Mann-Whitney U and KS) ---")
    p(f"{'Comparison':<45} {'n1':>4} {'n2':>4} {'MW p':>12} {'KS p':>12}")
    p("-" * 80)
    control_items = list(controls_mahal.items())
    pairs = [("Pre-LLM vs Post-LLM students", m_pre, m_post)]
    for name, vals in control_items:
        pairs.append((f"Pre-LLM students vs {name}", m_pre, vals))
        pairs.append((f"Post-LLM students vs {name}", m_post, vals))
    for i, (n1, v1) in enumerate(control_items):
        for n2, v2 in control_items[i + 1 :]:
            pairs.append((f"{n1} vs {n2}", v1, v2))
    for label, va, vb in pairs:
        _, mw_p = stats.mannwhitneyu(va, vb, alternative="two-sided")
        _, ks_p = stats.ks_2samp(va, vb)
        p(f"{label:<45} {len(va):>4} {len(vb):>4} {mw_p:>12.4e} {ks_p:>12.4e}")

    p("\n--- Individual year vs pre-LLM aggregate ---")
    p(f"{'Comparison':<40} {'n_yr':>5} {'mean':>7} {'MW p':>12} {'KS p':>12}")
    p("-" * 75)
    for yr in YEAR_ORDER:
        m_yr = mahal_fn(student_main[student_main["Academic Year"] == yr])
        if len(m_yr) == 0:
            continue
        _, mw_p = stats.mannwhitneyu(m_yr, m_pre, alternative="two-sided")
        _, ks_p = stats.ks_2samp(m_yr, m_pre)
        p(
            f"{yr + ' vs pre-LLM':<40} {len(m_yr):>5} {m_yr.mean():>7.3f} "
            f"{mw_p:>12.4e} {ks_p:>12.4e}"
        )

    p("\n--- Exceedance summary ---")
    p(
        f"{'Dataset':<30} {'n':>4}  {'mean':>6}  {'median':>7}  "
        f"{'>p=0.05':>9}  {'>p=0.01':>9}  {'max':>7}"
    )
    for label, vals in [
        ("Pre-LLM students", m_pre),
        ("Post-LLM students", m_post),
    ] + list(controls_mahal.items()):
        p(
            f"{label:<30} {len(vals):>4}  {vals.mean():>6.3f}  "
            f"{np.median(vals):>7.3f}  "
            f"{100 * (vals > thresh_05).mean():>8.0f}%  "
            f"{100 * (vals > thresh_01).mean():>8.0f}%  "
            f"{vals.max():>7.2f}"
        )

    p("\n--- Individual metric MW tests (pre-LLM vs each dataset) ---")
    for m in ["MATTR", "MTLD", "Burstiness R", "CV"]:
        p(f"\n  {m}:")
        pre_v = pre[m].dropna()
        for label, df in [("Post-LLM students", post)] + list(controls.items()):
            other = df[m].dropna()
            _, pm = stats.mannwhitneyu(pre_v, other, alternative="two-sided")
            p(
                f"    vs {label:<25}: p={pm:.4e}  "
                f"(pre={pre_v.mean():.4f}, other={other.mean():.4f})"
            )

    # Exposure estimate
    p("\n--- Simple exposure estimate (exceedance rate difference) ---")
    rate_pre = (m_pre > thresh_05).mean()
    rate_post = (m_post > thresh_05).mean()
    se_pre = np.sqrt(rate_pre * (1 - rate_pre) / len(m_pre))
    se_post = np.sqrt(rate_post * (1 - rate_post) / len(m_post))
    se_diff = np.sqrt(se_pre**2 + se_post**2)
    diff = rate_post - rate_pre
    p(f"  Pre-LLM exceedance rate:  {100 * rate_pre:.1f}%  ± {100 * se_pre:.1f} pp")
    p(f"  Post-LLM exceedance rate: {100 * rate_post:.1f}%  ± {100 * se_post:.1f} pp")
    p(f"  Difference (exposure est):{100 * diff:.1f}%  ± {100 * se_diff:.1f} pp (1σ)")

    # Power analysis for next cohort
    p(
        f"\n--- Power analysis: next cohort (n={NEXT_COHORT_N}, "
        f"assuming 2024/25 distribution) ---"
    )
    m_2425 = mahal_fn(student_main[student_main["Academic Year"] == "2024/2025"])
    np.random.seed(42)
    n_sim = 20000
    mw_ps = []
    for _ in range(n_sim):
        samp = np.random.choice(m_2425, size=NEXT_COHORT_N, replace=True)
        _, pv = stats.mannwhitneyu(samp, m_pre, alternative="two-sided")
        mw_ps.append(pv)
    mw_ps = np.array(mw_ps)
    p(f"  Median expected p-value:   {np.median(mw_ps):.4e}")
    p(f"  Power at p<0.05:           {100 * (mw_ps < 0.05).mean():.0f}%")
    p(f"  Power at p<0.01:           {100 * (mw_ps < 0.01).mean():.0f}%")
    p(f"  Power at p<0.001:          {100 * (mw_ps < 0.001).mean():.0f}%")
    p("=" * 72)

    path = os.path.join(output_dir, "stats_summary.txt")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"  Saved: {path}")


# =============================================================================
# MAIN
# =============================================================================


def main():
    args = parse_args()
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)
    print(f"\nOutput directory: {output_dir}/\n")

    include = [s.strip() for s in args.sheets.split(",")] if args.sheets else None
    exclude = (
        [s.strip() for s in args.exclude_sheets.split(",")]
        if args.exclude_sheets
        else None
    )

    student, controls = load_data(args.student, args.arxiv, include, exclude)
    colors = assign_control_colors(list(controls.keys()))
    markers = assign_control_markers(list(controls.keys()))

    student_main, pre, post, trans = split_cohorts(student)

    # self-built reference — always computed; needed for scatter display coordinates
    mean_3, std_3, corr_3, inv_corr = build_reference(pre)

    thresh_05 = np.sqrt(stats.chi2.ppf(0.95, df=3))
    thresh_01 = np.sqrt(stats.chi2.ppf(0.99, df=3))
    print(f"  p=0.05 threshold: {thresh_05:.4f}σ")
    print(f"  p=0.01 threshold: {thresh_01:.4f}σ")

    # Production calibration mode: load mu/sigma_inv from the Calibrations sheet
    # of an AI dashboard export.  σ values produced here match production exactly.
    # Scatter plot display coordinates still use the self-built standardised reference.
    if args.calibration_file:
        cal_mu, cal_sigma_inv = load_production_calibration(
            args.calibration_file,
            cal_type=args.calibration_type,
            cal_llm=args.calibration_llm,
        )
        def mahal_fn(df):  # noqa: E306
            return mahal_dist_production(df, cal_mu, cal_sigma_inv)
    else:
        def mahal_fn(df):  # noqa: E306
            return mahal_dist(df, mean_3, std_3, inv_corr)

    m_pre = mahal_fn(pre)
    m_post = mahal_fn(post)
    controls_mahal = {name: mahal_fn(df) for name, df in controls.items()}

    print("\nGenerating plots...")
    plot_violin_box(student_main, output_dir)
    plot_mahal_histograms(student_main, mahal_fn, thresh_05, thresh_01, output_dir)
    plot_mahal_kde(
        m_pre, m_post, controls_mahal, colors, thresh_05, thresh_01, output_dir
    )
    plot_scatters(
        pre,
        post,
        controls,
        colors,
        markers,
        mean_3,
        std_3,
        corr_3,
        inv_corr,
        thresh_05,
        thresh_01,
        output_dir,
    )
    plot_metric_kde(pre, post, controls, colors, output_dir)

    if args.scatter_specs:
        for plot_idx, spec in enumerate(args.scatter_specs):
            letter = chr(ord("d") + plot_idx)
            plot_custom_scatter(
                spec_str=spec,
                pre=pre,
                post=post,
                controls=controls,
                colors=colors,
                markers=markers,
                mean_3=mean_3,
                std_3=std_3,
                corr_3=corr_3,
                inv_corr=inv_corr,
                thresh_05=thresh_05,
                thresh_01=thresh_01,
                output_dir=output_dir,
                plot_letter=letter,
            )

    print("\nRunning statistical tests...")
    run_stats(
        pre,
        post,
        controls,
        controls_mahal,
        student_main,
        mahal_fn,
        thresh_05,
        thresh_01,
        output_dir,
    )

    print(f"\nDone. All outputs written to {output_dir}/")


if __name__ == "__main__":
    main()
