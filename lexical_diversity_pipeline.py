"""
Lexical Diversity Analysis Pipeline
====================================
Generates the full suite of plots and statistical tests for the
AI-use detection analysis based on MATTR, MTLD, Burstiness, and
Sentence CV metrics computed from student final-year project reports.

Usage
-----
    python lexical_diversity_pipeline.py

Configuration
-------------
Edit the CONFIGURATION block below to point to your data files and
adjust cohort definitions as new data arrives.

Dependencies
------------
    pandas, numpy, scipy, matplotlib
    Install with:  pip install pandas numpy scipy matplotlib openpyxl

Outputs (written to OUTPUT_DIR)
--------------------------------
    01_violin_boxplots.png          - Violin + box + strip plots per year
    02_mahal_histograms.png         - Mahalanobis distance histograms per year
    03_mahal_kde.png                - KDE of Mahalanobis distances, all datasets
    04a_scatter_students_zoom.png   - (MATTR+MTLD, CV) scatter, student core
    04b_scatter_students_full.png   - (MATTR+MTLD, CV) scatter, all outliers
    04c_scatter_all.png             - (MATTR+MTLD, CV) scatter, all datasets
    05_metric_kde.png               - KDE per metric, all datasets
    stats_summary.txt               - Statistical test results

Author notes
------------
Pipeline developed through iterative analysis in Claude.ai (April 2026).
Pre-LLM reference cohort: 2019/20, 2020/21, 2021/22 (n=148 complete cases).
Post-LLM cohort: 2023/24, 2024/25 (2022/23 treated as transitional).
Mahalanobis distance computed in standardised space (correlation matrix),
using MATTR, MTLD, and CV only (Burstiness excluded due to ~20% missingness).
"""

import pandas as pd
import numpy as np
from scipy import stats
from numpy.linalg import inv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import warnings
import os
import sys
warnings.filterwarnings('ignore')

# =============================================================================
# CONFIGURATION — edit this block when new data arrives
# =============================================================================

# Student report dashboard Excel file
STUDENT_FILE = 'AI_Dashboard_Global_2026-04-13_10-08-23.xlsx'

# arXiv control Excel file (two sheets: 'djs61' and 'astro-ph.CO')
ARXIV_FILE = 'arxiv_control_results.xlsx'

# Output directory for plots and stats
OUTPUT_DIR = 'pipeline_outputs'

# Cohort definitions
PRE_LLM_YEARS   = ['2019/2020', '2020/2021', '2021/2022']
POST_LLM_YEARS  = ['2023/2024', '2024/2025']
TRANS_YEARS     = ['2022/2023']
EXCLUDE_YEARS   = ['2025/2026']   # too small; add to POST_LLM_YEARS when complete

# Year display order and labels
YEAR_ORDER  = ['2019/2020','2020/2021','2021/2022','2022/2023','2023/2024','2024/2025']
YEAR_LABELS = ['2019/20',  '2020/21',  '2021/22',  '2022/23',  '2023/24',  '2024/25']

# Human academic normal ranges (from metric documentation)
HUMAN_NORMAL = {
    'MATTR':       (0.70, 0.85),
    'MTLD':        (70,   120),
    'Burstiness R':(0.20, 0.60),
    'CV':          (0.55, 0.85),
}

# Power analysis: expected size of next incoming cohort
NEXT_COHORT_N = 55   # 3 existing 2025/26 + 52 incoming

# =============================================================================
# COLOURS AND STYLE
# =============================================================================

PRE_COL   = '#4a6fa5'
POST_COL  = '#e07b39'
TRANS_COL = '#888888'
DJS_COL   = '#2ca02c'
ARX_COL   = '#9467bd'
HN_COL    = '#2255aa'

# =============================================================================
# LOAD DATA
# =============================================================================

def load_data():
    print("Loading data...")
    student = pd.read_excel(STUDENT_FILE, header=0)
    djs     = pd.read_excel(ARXIV_FILE, sheet_name='djs61')
    arxiv   = pd.read_excel(ARXIV_FILE, sheet_name='astro-ph.CO')
    for df in [djs, arxiv]:
        df.rename(columns={'mattr':'MATTR','mtld':'MTLD',
                           'burstiness':'Burstiness R','sentence_cv':'CV'}, inplace=True)
    print(f"  Student records: {len(student)}")
    print(f"  djs61 records:   {len(djs)}")
    print(f"  astro-ph.CO:     {len(arxiv)}")
    return student, djs, arxiv


def split_cohorts(student):
    student_main = student[~student['Academic Year'].isin(EXCLUDE_YEARS)].copy()
    pre   = student_main[student_main['Academic Year'].isin(PRE_LLM_YEARS)]
    post  = student_main[student_main['Academic Year'].isin(POST_LLM_YEARS)]
    trans = student_main[student_main['Academic Year'].isin(TRANS_YEARS)]
    return student_main, pre, post, trans

# =============================================================================
# MAHALANOBIS DISTANCE (standardised / correlation-based)
# =============================================================================

def build_reference(pre):
    """Estimate centroid and inverse correlation matrix from pre-LLM cohort."""
    pre_3    = pre.dropna(subset=['MATTR','MTLD','CV'])[['MATTR','MTLD','CV']]
    mean_3   = pre_3.mean().values
    std_3    = pre_3.std().values
    corr_3   = np.corrcoef(pre_3.T)
    inv_corr = inv(corr_3)
    cond_num = np.linalg.cond(corr_3)
    print(f"\nPre-LLM reference (n={len(pre_3)} complete cases):")
    print(f"  Centroid: MATTR={mean_3[0]:.6f}, MTLD={mean_3[1]:.4f}, CV={mean_3[2]:.6f}")
    print(f"  Correlation matrix condition number: {cond_num:.2f}  (well-conditioned < 100)")
    return mean_3, std_3, corr_3, inv_corr


def mahal_dist(df, mean_3, std_3, inv_corr):
    sub = df.dropna(subset=['MATTR','MTLD','CV'])[['MATTR','MTLD','CV']]
    def _d(row):
        z = (row.values - mean_3) / std_3
        return np.sqrt(z @ inv_corr @ z)
    return sub.apply(_d, axis=1).values


def display_coords(df, mean_3, std_3, inv_corr):
    """Return (x_combined, y_cv, mahalanobis) for scatter plots."""
    sub = df.dropna(subset=['MATTR','MTLD','CV'])[['MATTR','MTLD','CV']].copy()
    x = ((sub['MATTR'] - mean_3[0]) / std_3[0] +
         (sub['MTLD']  - mean_3[1]) / std_3[1]) / np.sqrt(2)
    y = (sub['CV'] - mean_3[2]) / std_3[2]
    mah = sub.apply(lambda r: np.sqrt(
        ((r.values - mean_3) / std_3) @ inv_corr @ ((r.values - mean_3) / std_3)
    ), axis=1).values
    return x.values, y.values, mah


def build_ellipses(corr_3, thresh_05, thresh_01):
    """Build 2D confidence ellipses for the (MATTR+MTLD, CV) display space."""
    T = np.array([[1/np.sqrt(2), 1/np.sqrt(2), 0], [0, 0, 1]])
    Sigma_2d = T @ corr_3 @ T.T
    eigvals_2d, eigvecs_2d = np.linalg.eigh(Sigma_2d)
    eigvals_2d = eigvals_2d[::-1]; eigvecs_2d = eigvecs_2d[:, ::-1]

    def _ellipse(thresh):
        thresh_2d = np.sqrt(stats.chi2.ppf(stats.chi2.cdf(thresh**2, df=3), df=2))
        a = np.sqrt(eigvals_2d[0]) * thresh_2d
        b = np.sqrt(eigvals_2d[1]) * thresh_2d
        angle = np.arctan2(eigvecs_2d[1,0], eigvecs_2d[0,0])
        theta = np.linspace(0, 2*np.pi, 500)
        c, s  = np.cos(angle), np.sin(angle)
        xe, ye = a*np.cos(theta), b*np.sin(theta)
        return c*xe - s*ye, s*xe + c*ye

    return _ellipse(thresh_05), _ellipse(thresh_01)

# =============================================================================
# PLOT 1: VIOLIN + BOX + STRIP PLOTS
# =============================================================================

def plot_violin_box(student_main, output_dir):
    metrics       = ['MATTR','MTLD','Burstiness R','CV']
    metric_labels = ['MATTR','MTLD','Burstiness B','Sentence CV']

    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    fig.patch.set_facecolor('#fafafa')
    axes = axes.flatten()

    for ax, m, ml in zip(axes, metrics, metric_labels):
        ax.set_facecolor('#f7f7f7')
        lo, hi = HUMAN_NORMAL[m]
        ax.axhspan(lo, hi, alpha=0.10, color='green', zorder=0)
        ax.axhline(lo, color='green', lw=0.8, ls='--', alpha=0.5)
        ax.axhline(hi, color='green', lw=0.8, ls='--', alpha=0.5)
        ax.axvline(2.5, color='#e74c3c', lw=1.5, ls=':', alpha=0.7)

        data_by_year = [student_main[student_main['Academic Year']==yr][m].dropna().values
                        for yr in YEAR_ORDER]
        colors_v = [PRE_COL if yr in PRE_LLM_YEARS else
                    (TRANS_COL if yr in TRANS_YEARS else POST_COL)
                    for yr in YEAR_ORDER]

        parts = ax.violinplot(data_by_year, positions=range(len(YEAR_ORDER)),
                              showmedians=True, showextrema=False)
        for pc, col in zip(parts['bodies'], colors_v):
            pc.set_facecolor(col); pc.set_alpha(0.45)
            pc.set_edgecolor('grey'); pc.set_linewidth(0.5)
        parts['cmedians'].set_color('#222222'); parts['cmedians'].set_linewidth(1.8)

        bp = ax.boxplot(data_by_year, positions=range(len(YEAR_ORDER)), widths=0.18,
                        patch_artist=True, showfliers=False,
                        medianprops=dict(color='#222222', linewidth=0),
                        whiskerprops=dict(linewidth=0.8, color='#555555'),
                        capprops=dict(linewidth=0.8, color='#555555'),
                        boxprops=dict(linewidth=0.8))
        for patch, col in zip(bp['boxes'], colors_v):
            patch.set_facecolor(col); patch.set_alpha(0.75)

        for j, (yr, col) in enumerate(zip(YEAR_ORDER, colors_v)):
            vals = student_main[student_main['Academic Year']==yr][m].dropna().values
            jitter = np.random.RandomState(42+j).uniform(-0.12, 0.12, len(vals))
            ax.scatter(j + jitter, vals, color=col, alpha=0.30, s=10, zorder=3, linewidths=0)

        ax.set_xticks(range(len(YEAR_ORDER)))
        ax.set_xticklabels(YEAR_LABELS, fontsize=8.5)
        ax.set_title(ml, fontsize=11, fontweight='bold', pad=4)
        ax.tick_params(axis='y', labelsize=8)
        ax.spines[['top','right']].set_visible(False)

    legend_els = [
        mpatches.Patch(facecolor=PRE_COL,   alpha=0.7, label='Pre-LLM'),
        mpatches.Patch(facecolor=TRANS_COL, alpha=0.7, label='Transitional (2022/23)'),
        mpatches.Patch(facecolor=POST_COL,  alpha=0.7, label='Post-LLM'),
        mpatches.Patch(facecolor='green',   alpha=0.2, label='Human academic normal range'),
    ]
    fig.legend(handles=legend_els, loc='lower center', ncol=4, fontsize=9,
               bbox_to_anchor=(0.5, -0.02), framealpha=0.95, edgecolor='#cccccc')
    fig.suptitle('Lexical Diversity Metrics by Academic Year',
                 fontsize=13, fontweight='bold', color='#1a1a2e')
    plt.tight_layout(rect=[0, 0.04, 1, 0.97])
    path = os.path.join(output_dir, '01_violin_boxplots.png')
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#fafafa')
    plt.close()
    print(f"  Saved: {path}")

# =============================================================================
# PLOT 2: MAHALANOBIS HISTOGRAMS PER YEAR
# =============================================================================

def plot_mahal_histograms(student_main, mean_3, std_3, inv_corr,
                          thresh_05, thresh_01, output_dir):
    all_vals  = [mahal_dist(student_main[student_main['Academic Year']==yr],
                            mean_3, std_3, inv_corr) for yr in YEAR_ORDER]
    global_max = max(v.max() for v in all_vals)
    x_max      = global_max * 1.08
    x_ref      = np.linspace(0, x_max, 400)
    chi_pdf    = stats.chi.pdf(x_ref, df=3)

    fig, axes = plt.subplots(2, 3, figsize=(15, 9))
    fig.patch.set_facecolor('#fafafa')
    axes = axes.flatten()

    for i, (yr, lbl, vals) in enumerate(zip(YEAR_ORDER, YEAR_LABELS, all_vals)):
        ax  = axes[i]
        ax.set_facecolor('#f7f7f7')
        col = PRE_COL if yr in PRE_LLM_YEARS else \
              (TRANS_COL if yr in TRANS_YEARS else POST_COL)
        era = 'Pre-LLM' if yr in PRE_LLM_YEARS else \
              ('Transitional' if yr in TRANS_YEARS else 'Post-LLM')

        ax.plot(x_ref, chi_pdf * len(vals) * 0.45, color='#aaaaaa',
                lw=1.2, ls='--')
        bins = np.linspace(0, x_max, 26)
        n, edges, patches = ax.hist(vals, bins=bins, color=col, alpha=0.60,
                                    edgecolor='white', linewidth=0.5, zorder=2)
        for patch, left in zip(patches, edges[:-1]):
            if left >= thresh_01:
                patch.set_facecolor('#7f0000'); patch.set_alpha(0.85)
            elif left >= thresh_05:
                patch.set_facecolor('#c0392b'); patch.set_alpha(0.75)

        ax.axvline(thresh_05, color='#c0392b', lw=1.5, ls=':', zorder=4)
        ax.axvline(thresh_01, color='#7f0000', lw=1.2, ls=':', zorder=4)
        ax.axvline(np.mean(vals),   color=col, lw=2.0, ls='-',  zorder=5, alpha=0.9)
        ax.axvline(np.median(vals), color=col, lw=1.5, ls='--', zorder=5, alpha=0.7)

        n05 = (vals > thresh_05).sum(); pct05 = 100*n05/len(vals)
        n01 = (vals > thresh_01).sum(); pct01 = 100*n01/len(vals)
        ax.text(0.97, 0.97,
                f'n={len(vals)}\nmean={np.mean(vals):.2f}\n'
                f'median={np.median(vals):.2f}\n'
                f'>p0.05: {n05} ({pct05:.0f}%)\n>p0.01: {n01} ({pct01:.0f}%)',
                transform=ax.transAxes, ha='right', va='top', fontsize=8.0,
                family='monospace',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                          alpha=0.85, edgecolor='#ccc'))
        ax.set_title(f'{lbl}  [{era}]', fontsize=10, fontweight='bold', color=col)
        ax.set_xlabel('Mahalanobis distance from pre-LLM centroid', fontsize=8)
        ax.set_ylabel('Count', fontsize=8)
        ax.set_xlim(0, x_max); ax.tick_params(labelsize=8)
        ax.spines[['top','right']].set_visible(False)

    legend_els = [
        mpatches.Patch(facecolor=PRE_COL,   alpha=0.7,  label='Pre-LLM cohort'),
        mpatches.Patch(facecolor=TRANS_COL, alpha=0.7,  label='Transitional (2022/23)'),
        mpatches.Patch(facecolor=POST_COL,  alpha=0.7,  label='Post-LLM cohort'),
        mpatches.Patch(facecolor='#c0392b', alpha=0.75, label='p=0.05 to p=0.01'),
        mpatches.Patch(facecolor='#7f0000', alpha=0.85, label='Beyond p=0.01'),
        Line2D([0],[0], color='grey', lw=2.0, ls='-',   label='Cohort mean'),
        Line2D([0],[0], color='grey', lw=1.5, ls='--',  label='Cohort median'),
        Line2D([0],[0], color='#aaaaaa', lw=1.2, ls='--', label='χ(3) null reference'),
    ]
    fig.legend(handles=legend_els, loc='lower center', ncol=4, fontsize=8.5,
               bbox_to_anchor=(0.5, -0.04), framealpha=0.95, edgecolor='#cccccc')
    fig.suptitle(f'Mahalanobis Distance Distributions by Academic Year\n'
                 f'Reference: pre-LLM centroid;  '
                 f'p=0.05→{thresh_05:.2f}σ,  p=0.01→{thresh_01:.2f}σ  '
                 f'(x-axis to {x_max:.1f}σ)',
                 fontsize=11, fontweight='bold', color='#1a1a2e')
    plt.tight_layout(rect=[0, 0.06, 1, 0.95])
    path = os.path.join(output_dir, '02_mahal_histograms.png')
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#fafafa')
    plt.close()
    print(f"  Saved: {path}")

# =============================================================================
# PLOT 3: KDE OF MAHALANOBIS DISTANCES
# =============================================================================

def plot_mahal_kde(m_pre, m_post, m_djs, m_arx, thresh_05, thresh_01, output_dir):
    datasets_kd = {
        'Pre-LLM students':         (m_pre,  PRE_COL,  'solid',  2.2),
        'Post-LLM students':        (m_post, POST_COL, 'solid',  2.2),
        'djs61 (personal arXiv)':   (m_djs,  DJS_COL,  'dashed', 2.0),
        'astro-ph.CO (arXiv n=200)':(m_arx,  ARX_COL,  'dashed', 2.0),
    }
    x_ref   = np.linspace(0, 10, 400)
    chi_pdf = stats.chi.pdf(x_ref, df=3)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    fig.patch.set_facecolor('#fafafa')

    for ax, (xlim, title) in zip(axes, [
            ((0, 8),  'KDE of Mahalanobis distances'),
            ((0, 14), 'Extended range (arXiv scale)')]):
        ax.set_facecolor('#f7f7f7')
        ax.plot(x_ref, chi_pdf*0.5, color='#aaaaaa', lw=1.2, ls=':')
        ax.axvline(thresh_05, color='#c0392b', lw=1.5, ls='--', alpha=0.8)
        ax.axvline(thresh_01, color='#7f0000', lw=1.2, ls='--', alpha=0.7)
        for label, (vals, col, ls, lw) in datasets_kd.items():
            kde_x = np.linspace(0, xlim[1], 400)
            kde   = stats.gaussian_kde(vals, bw_method=0.35)
            ax.plot(kde_x, kde(kde_x), color=col, lw=lw, ls=ls, alpha=0.85, label=label)
            ax.axvline(np.mean(vals), color=col, lw=0.9, ls=':', alpha=0.55)
        rows = [f"{lb[:28]:<28}  mean={v.mean():.2f}  >p05={100*(v>thresh_05).mean():.0f}%"
                for lb, (v,*_) in datasets_kd.items()]
        ax.text(0.97, 0.97, '\n'.join(rows), transform=ax.transAxes,
                ha='right', va='top', fontsize=7.0, family='monospace',
                bbox=dict(boxstyle='round,pad=0.35', facecolor='white',
                          alpha=0.85, edgecolor='#ccc'))
        ax.set_xlim(xlim); ax.set_ylim(bottom=0)
        ax.set_xlabel('Mahalanobis distance from pre-LLM centroid', fontsize=9)
        ax.set_ylabel('Density', fontsize=9)
        ax.set_title(title, fontsize=10, fontweight='bold')
        ax.spines[['top','right']].set_visible(False); ax.tick_params(labelsize=8)

    legend_els = [
        Line2D([0],[0], color=PRE_COL,  lw=2.2, ls='solid',  label='Pre-LLM students'),
        Line2D([0],[0], color=POST_COL, lw=2.2, ls='solid',  label='Post-LLM students'),
        Line2D([0],[0], color=DJS_COL,  lw=2.0, ls='dashed', label='djs61'),
        Line2D([0],[0], color=ARX_COL,  lw=2.0, ls='dashed', label='astro-ph.CO'),
        Line2D([0],[0], color='#aaaaaa',lw=1.2, ls=':',      label='χ(3) null reference'),
        Line2D([0],[0], color='#c0392b',lw=1.5, ls='--',     label=f'p=0.05 ({thresh_05:.2f}σ)'),
    ]
    fig.legend(handles=legend_els, loc='lower center', ncol=3, fontsize=9,
               bbox_to_anchor=(0.5, -0.10), framealpha=0.95, edgecolor='#cccccc')
    fig.suptitle('Mahalanobis Distance KDE', fontsize=12, fontweight='bold', color='#1a1a2e')
    plt.tight_layout(rect=[0, 0.08, 1, 0.96])
    path = os.path.join(output_dir, '03_mahal_kde.png')
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#fafafa')
    plt.close()
    print(f"  Saved: {path}")

# =============================================================================
# SCATTER PLOT HELPER FUNCTIONS
# =============================================================================

def _draw_scatter_base(ax, xlim, ylim, e05, e01, x_norm_lo, x_norm_hi,
                        z_cv_lo, z_cv_hi, thresh_05, thresh_01):
    ax.set_facecolor('#f7f7f7')
    # Human-normal bands first (lowest zorder)
    ax.axvspan(x_norm_lo, x_norm_hi, alpha=0.13, color=HN_COL, zorder=1)
    ax.axhspan(z_cv_lo,   z_cv_hi,   alpha=0.13, color=HN_COL, zorder=1)
    # Confidence regions — no fill beyond p=0.01
    ax.fill(e01[0], e01[1], color='#fef0cd', zorder=2)
    ax.fill(e05[0], e05[1], color='#eef5ee', zorder=3)
    ax.plot(e05[0], e05[1], color='#c0392b', lw=1.8, ls='--', zorder=5)
    ax.plot(e01[0], e01[1], color='#7f0000', lw=1.5, ls='--', zorder=5)
    ax.axhline(0, color='#aaaaaa', lw=0.7, ls=':', zorder=4)
    ax.axvline(0, color='#aaaaaa', lw=0.7, ls=':', zorder=4)
    ax.set_xlim(xlim); ax.set_ylim(ylim)
    ax.set_xlabel('Standardised (MATTR+MTLD)/√2\n← lower diversity          higher diversity →',
                  fontsize=8.5)
    ax.set_ylabel('Standardised CV\n← uniform          variable →', fontsize=8.5)
    ax.spines[['top','right']].set_visible(False); ax.tick_params(labelsize=8)


def _plot_scatter_points(ax, df, col, mk, al, sz, label,
                          mean_3, std_3, inv_corr, thresh_05, thresh_01):
    x, y, mah = display_coords(df, mean_3, std_3, inv_corr)
    b01 = mah > thresh_01; b05 = (mah > thresh_05) & ~b01; ins = mah <= thresh_05
    ax.scatter(x[ins],  y[ins],  c=col, marker=mk, s=sz,     alpha=al,  zorder=6,
               linewidths=0.3, edgecolors='white', label=label)
    ax.scatter(x[b05],  y[b05],  c=col, marker=mk, s=sz*2.0, alpha=0.9, zorder=7,
               linewidths=1.0, edgecolors='#c0392b')
    ax.scatter(x[b01],  y[b01],  c=col, marker=mk, s=sz*2.5, alpha=1.0, zorder=8,
               linewidths=1.4, edgecolors='#7f0000')
    for xi, yi, mi in zip(x, y, mah):
        if mi > thresh_01:
            ax.annotate(f'{mi:.1f}σ', (xi, yi), textcoords='offset points',
                        xytext=(6,4), fontsize=7.5, color='#7f0000',
                        fontweight='bold', zorder=9)


def _scatter_legend():
    return [
        mpatches.Patch(color='#eef5ee',  label='Inside p=0.05'),
        mpatches.Patch(color='#fef0cd',  label='p=0.05 to p=0.01'),
        Line2D([0],[0], color='#c0392b', lw=1.8, ls='--', label='p=0.05 contour'),
        Line2D([0],[0], color='#7f0000', lw=1.5, ls='--', label='p=0.01 contour'),
        mpatches.Patch(color=PRE_COL,    alpha=0.7, label='Pre-LLM students'),
        mpatches.Patch(color=POST_COL,   alpha=0.7, label='Post-LLM students'),
        mpatches.Patch(color=DJS_COL,    alpha=0.7, label='djs61'),
        mpatches.Patch(color=ARX_COL,    alpha=0.7, label='astro-ph.CO'),
        mpatches.Patch(color=HN_COL,     alpha=0.25,label='Human academic normal range'),
        Line2D([0],[0], marker='o', color='w', markerfacecolor='grey', markersize=8,
               markeredgecolor='#7f0000', markeredgewidth=1.4,
               label='Beyond p=0.01 (σ labelled)'),
    ]

# =============================================================================
# PLOTS 4a, 4b, 4c: SCATTER PLOTS
# =============================================================================

def plot_scatters(pre, post, djs, arxiv, mean_3, std_3, corr_3, inv_corr,
                  thresh_05, thresh_01, output_dir):
    e05, e01 = build_ellipses(corr_3, thresh_05, thresh_01)

    # Human-normal bands in display coordinates
    x_norm_lo = ((0.70-mean_3[0])/std_3[0] + (70 -mean_3[1])/std_3[1]) / np.sqrt(2)
    x_norm_hi = ((0.85-mean_3[0])/std_3[0] + (120-mean_3[1])/std_3[1]) / np.sqrt(2)
    z_cv_lo   = (0.55 - mean_3[2]) / std_3[2]
    z_cv_hi   = (0.85 - mean_3[2]) / std_3[2]

    # Compute axis limits
    all_student = pd.concat([pre, post])
    xs, ys, _ = display_coords(all_student, mean_3, std_3, inv_corr)
    xd, yd, _ = display_coords(djs,   mean_3, std_3, inv_corr)
    xa, ya, _ = display_coords(arxiv, mean_3, std_3, inv_corr)
    pad = 0.6

    xlim_zoom = (-4.5, 4.5); ylim_zoom = (-2.5, 4.5)
    xlim_full = (xs.min()-pad, xs.max()+pad); ylim_full = (ys.min()-pad, ys.max()+pad)
    xlim_arx  = (min(xs.min(),xd.min(),xa.min())-pad,
                 max(xs.max(),xd.max(),xa.max())+pad)
    ylim_arx  = (min(ys.min(),yd.min(),ya.min())-pad,
                 max(ys.max(),yd.max(),ya.max())+pad)

    n_pre  = len(pre.dropna(subset=['MATTR','MTLD','CV']))
    n_post = len(post.dropna(subset=['MATTR','MTLD','CV']))
    base_kw = dict(mean_3=mean_3, std_3=std_3, inv_corr=inv_corr,
                   thresh_05=thresh_05, thresh_01=thresh_01)
    ell_kw  = dict(e05=e05, e01=e01, x_norm_lo=x_norm_lo, x_norm_hi=x_norm_hi,
                   z_cv_lo=z_cv_lo, z_cv_hi=z_cv_hi,
                   thresh_05=thresh_05, thresh_01=thresh_01)
    leg = _scatter_legend()

    def _hn_labels(ax, xlim, ylim):
        ax.text(x_norm_lo+0.1, ylim[1]-0.25, 'human-normal\nMATTR+MTLD',
                fontsize=7.5, color=HN_COL, style='italic', va='top', zorder=10)
        ax.text(xlim[0]+0.15, z_cv_lo+0.12, 'human-normal CV',
                fontsize=7.5, color=HN_COL, style='italic', zorder=10)

    # 4a: students zoomed
    fig, ax = plt.subplots(figsize=(9, 8)); fig.patch.set_facecolor('#fafafa')
    _draw_scatter_base(ax, xlim_zoom, ylim_zoom, **ell_kw)
    _plot_scatter_points(ax, pre,  PRE_COL,  'o', 0.50, 30,
                         f'Pre-LLM students (n={n_pre})',  **base_kw)
    _plot_scatter_points(ax, post, POST_COL, 'o', 0.75, 36,
                         f'Post-LLM students (n={n_post})', **base_kw)
    _hn_labels(ax, xlim_zoom, ylim_zoom)
    ax.set_title('Student cohorts — central region', fontsize=10, fontweight='bold')
    fig.legend(handles=leg[:8]+[leg[8],leg[9]], loc='lower center', ncol=4,
               fontsize=8.5, bbox_to_anchor=(0.5,-0.08),
               framealpha=0.95, edgecolor='#cccccc')
    plt.tight_layout(rect=[0,0.09,1,1])
    path = os.path.join(output_dir, '04a_scatter_students_zoom.png')
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#fafafa')
    plt.close(); print(f"  Saved: {path}")

    # 4b: students full extent
    fig, ax = plt.subplots(figsize=(10, 9)); fig.patch.set_facecolor('#fafafa')
    _draw_scatter_base(ax, xlim_full, ylim_full, **ell_kw)
    _plot_scatter_points(ax, pre,  PRE_COL,  'o', 0.50, 30,
                         f'Pre-LLM students (n={n_pre})',  **base_kw)
    _plot_scatter_points(ax, post, POST_COL, 'o', 0.75, 36,
                         f'Post-LLM students (n={n_post})', **base_kw)
    _hn_labels(ax, xlim_full, ylim_full)
    ax.set_title('Student cohorts — all outliers included', fontsize=10, fontweight='bold')
    fig.legend(handles=leg[:8]+[leg[8],leg[9]], loc='lower center', ncol=4,
               fontsize=8.5, bbox_to_anchor=(0.5,-0.08),
               framealpha=0.95, edgecolor='#cccccc')
    plt.tight_layout(rect=[0,0.09,1,1])
    path = os.path.join(output_dir, '04b_scatter_students_full.png')
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#fafafa')
    plt.close(); print(f"  Saved: {path}")

    # 4c: all datasets
    fig, ax = plt.subplots(figsize=(11, 9)); fig.patch.set_facecolor('#fafafa')
    _draw_scatter_base(ax, xlim_arx, ylim_arx, **ell_kw)
    _plot_scatter_points(ax, pre,   PRE_COL,  'o', 0.45, 25, 'Pre-LLM students', **base_kw)
    _plot_scatter_points(ax, post,  POST_COL, 'o', 0.65, 30, 'Post-LLM students', **base_kw)
    _plot_scatter_points(ax, djs,   DJS_COL,  's', 0.80, 36, 'djs61', **base_kw)
    _plot_scatter_points(ax, arxiv, ARX_COL,  '^', 0.45, 20, 'astro-ph.CO', **base_kw)
    _hn_labels(ax, xlim_arx, ylim_arx)
    ax.set_title('All datasets — students + arXiv controls', fontsize=10, fontweight='bold')
    fig.legend(handles=leg, loc='lower center', ncol=4, fontsize=8.5,
               bbox_to_anchor=(0.5,-0.10), framealpha=0.95, edgecolor='#cccccc')
    plt.tight_layout(rect=[0,0.11,1,1])
    path = os.path.join(output_dir, '04c_scatter_all.png')
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#fafafa')
    plt.close(); print(f"  Saved: {path}")

# =============================================================================
# PLOT 5: METRIC KDE
# =============================================================================

def plot_metric_kde(pre, post, djs, arxiv, output_dir):
    datasets = {
        'Pre-LLM students (2019–2022)': (pre,   PRE_COL,  'solid',  2.2),
        'Post-LLM students (2023–2025)':(post,  POST_COL, 'solid',  2.2),
        'djs61 (personal arXiv)':       (djs,   DJS_COL,  'dashed', 2.0),
        'astro-ph.CO (arXiv n=200)':    (arxiv, ARX_COL,  'dashed', 2.0),
    }
    metrics       = ['MATTR','MTLD','Burstiness R','CV']
    metric_labels = ['MATTR','MTLD','Burstiness B','Sentence CV']
    xlims = {'MATTR':(0.48,0.82), 'MTLD':(20,135),
             'Burstiness R':(-0.35,0.55), 'CV':(0.30,1.80)}

    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    fig.patch.set_facecolor('#fafafa')
    axes = axes.flatten()

    for ax, m, ml in zip(axes, metrics, metric_labels):
        ax.set_facecolor('#f7f7f7')
        lo, hi = HUMAN_NORMAL[m]
        ax.axvspan(lo, hi, alpha=0.10, color='green', zorder=0)
        ax.axvline(lo, color='green', lw=0.8, ls='--', alpha=0.5)
        ax.axvline(hi, color='green', lw=0.8, ls='--', alpha=0.5)
        kde_x = np.linspace(*xlims[m], 400)
        for label, (df, col, ls, lw) in datasets.items():
            vals = df[m].dropna().values
            if len(vals) < 5: continue
            kde = stats.gaussian_kde(vals, bw_method=0.4)
            ax.plot(kde_x, kde(kde_x), color=col, lw=lw, ls=ls, alpha=0.85,
                    label=f'{label}  (n={len(vals)})')
            ax.axvline(vals.mean(), color=col, lw=0.9, ls=':', alpha=0.6)
        ax.set_xlim(xlims[m]); ax.set_ylim(bottom=0)
        ax.set_xlabel(ml, fontsize=10); ax.set_ylabel('Density', fontsize=9)
        ax.set_title(ml, fontsize=12, fontweight='bold', pad=5)
        ax.spines[['top','right']].set_visible(False); ax.tick_params(labelsize=8.5)
        ymax = ax.get_ylim()[1]
        ax.text((lo+hi)/2, ymax*0.92, 'human\nnormal', ha='center', va='top',
                fontsize=7.5, color='green', alpha=0.7, style='italic')

    legend_els = [
        Line2D([0],[0], color=PRE_COL,  lw=2.2, ls='solid',  label='Pre-LLM students'),
        Line2D([0],[0], color=POST_COL, lw=2.2, ls='solid',  label='Post-LLM students'),
        Line2D([0],[0], color=DJS_COL,  lw=2.0, ls='dashed', label='djs61'),
        Line2D([0],[0], color=ARX_COL,  lw=2.0, ls='dashed', label='astro-ph.CO'),
        mpatches.Patch(facecolor='green', alpha=0.2, label='Human academic normal range'),
        Line2D([0],[0], color='grey', lw=0.9, ls=':', label='Dataset mean'),
    ]
    fig.legend(handles=legend_els, loc='lower center', ncol=3, fontsize=9.5,
               bbox_to_anchor=(0.5, -0.03), framealpha=0.95, edgecolor='#cccccc')
    fig.suptitle('KDE of Individual Metric Distributions',
                 fontsize=13, fontweight='bold', color='#1a1a2e')
    plt.tight_layout(rect=[0, 0.05, 1, 0.97])
    path = os.path.join(output_dir, '05_metric_kde.png')
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#fafafa')
    plt.close()
    print(f"  Saved: {path}")

# =============================================================================
# STATISTICAL TESTS
# =============================================================================

def run_stats(pre, post, djs, arxiv, student_main,
              mean_3, std_3, inv_corr, thresh_05, thresh_01, output_dir):
    lines = []
    def p(s): lines.append(s); print(s)

    m_pre  = mahal_dist(pre,   mean_3, std_3, inv_corr)
    m_post = mahal_dist(post,  mean_3, std_3, inv_corr)
    m_djs  = mahal_dist(djs,   mean_3, std_3, inv_corr)
    m_arx  = mahal_dist(arxiv, mean_3, std_3, inv_corr)

    p("=" * 72)
    p("STATISTICAL TESTS ON MAHALANOBIS DISTANCE DISTRIBUTIONS")
    p("=" * 72)

    p("\n--- Pairwise comparisons (Mann-Whitney U and KS) ---")
    p(f"{'Comparison':<45} {'n1':>4} {'n2':>4} {'MW p':>12} {'KS p':>12}")
    p("-"*80)
    pairs = [
        ('Pre-LLM vs Post-LLM students',  m_pre,  m_post),
        ('Pre-LLM students vs djs61',      m_pre,  m_djs),
        ('Pre-LLM students vs astro-ph.CO',m_pre,  m_arx),
        ('Post-LLM students vs djs61',     m_post, m_djs),
        ('Post-LLM students vs astro-ph.CO',m_post,m_arx),
        ('djs61 vs astro-ph.CO',           m_djs,  m_arx),
    ]
    for label, va, vb in pairs:
        _, mw_p = stats.mannwhitneyu(va, vb, alternative='two-sided')
        _, ks_p = stats.ks_2samp(va, vb)
        p(f"{label:<45} {len(va):>4} {len(vb):>4} {mw_p:>12.4e} {ks_p:>12.4e}")

    p("\n--- Individual year vs pre-LLM aggregate ---")
    p(f"{'Comparison':<40} {'n_yr':>5} {'mean':>7} {'MW p':>12} {'KS p':>12}")
    p("-"*75)
    for yr in YEAR_ORDER:
        m_yr = mahal_dist(student_main[student_main['Academic Year']==yr],
                          mean_3, std_3, inv_corr)
        if len(m_yr) == 0: continue
        _, mw_p = stats.mannwhitneyu(m_yr, m_pre, alternative='two-sided')
        _, ks_p = stats.ks_2samp(m_yr, m_pre)
        p(f"{yr+' vs pre-LLM':<40} {len(m_yr):>5} {m_yr.mean():>7.3f} "
          f"{mw_p:>12.4e} {ks_p:>12.4e}")

    p("\n--- Exceedance summary ---")
    p(f"{'Dataset':<30} {'n':>4}  {'mean':>6}  {'median':>7}  "
      f"{'>p=0.05':>9}  {'>p=0.01':>9}  {'max':>7}")
    for label, vals in [('Pre-LLM students', m_pre),
                         ('Post-LLM students', m_post),
                         ('djs61', m_djs), ('astro-ph.CO', m_arx)]:
        p(f"{label:<30} {len(vals):>4}  {vals.mean():>6.3f}  "
          f"{np.median(vals):>7.3f}  "
          f"{100*(vals>thresh_05).mean():>8.0f}%  "
          f"{100*(vals>thresh_01).mean():>8.0f}%  "
          f"{vals.max():>7.2f}")

    p("\n--- Individual metric MW tests (pre-LLM vs each dataset) ---")
    for m in ['MATTR','MTLD','Burstiness R','CV']:
        p(f"\n  {m}:")
        pre_v = pre[m].dropna()
        for label, df in [('Post-LLM students', post),
                           ('djs61', djs), ('astro-ph.CO', arxiv)]:
            other = df[m].dropna()
            _, pm = stats.mannwhitneyu(pre_v, other, alternative='two-sided')
            p(f"    vs {label:<25}: p={pm:.4e}  "
              f"(pre={pre_v.mean():.4f}, other={other.mean():.4f})")

    # Exposure estimate
    p("\n--- Simple exposure estimate (exceedance rate difference) ---")
    rate_pre  = (m_pre  > thresh_05).mean()
    rate_post = (m_post > thresh_05).mean()
    se_pre    = np.sqrt(rate_pre *(1-rate_pre) /len(m_pre))
    se_post   = np.sqrt(rate_post*(1-rate_post)/len(m_post))
    se_diff   = np.sqrt(se_pre**2 + se_post**2)
    diff      = rate_post - rate_pre
    p(f"  Pre-LLM exceedance rate:  {100*rate_pre:.1f}%  ± {100*se_pre:.1f} pp")
    p(f"  Post-LLM exceedance rate: {100*rate_post:.1f}%  ± {100*se_post:.1f} pp")
    p(f"  Difference (exposure est):{100*diff:.1f}%  ± {100*se_diff:.1f} pp (1σ)")

    # Power analysis for next cohort
    p(f"\n--- Power analysis: next cohort (n={NEXT_COHORT_N}, "
      f"assuming 2024/25 distribution) ---")
    m_2425 = mahal_dist(student_main[student_main['Academic Year']=='2024/2025'],
                        mean_3, std_3, inv_corr)
    np.random.seed(42)
    n_sim  = 20000
    mw_ps  = []
    for _ in range(n_sim):
        samp = np.random.choice(m_2425, size=NEXT_COHORT_N, replace=True)
        _, pv = stats.mannwhitneyu(samp, m_pre, alternative='two-sided')
        mw_ps.append(pv)
    mw_ps = np.array(mw_ps)
    p(f"  Median expected p-value:   {np.median(mw_ps):.4e}")
    p(f"  Power at p<0.05:           {100*(mw_ps<0.05).mean():.0f}%")
    p(f"  Power at p<0.01:           {100*(mw_ps<0.01).mean():.0f}%")
    p(f"  Power at p<0.001:          {100*(mw_ps<0.001).mean():.0f}%")
    p("=" * 72)

    path = os.path.join(output_dir, 'stats_summary.txt')
    with open(path, 'w') as f:
        f.write('\n'.join(lines))
    print(f"  Saved: {path}")

# =============================================================================
# MAIN
# =============================================================================

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"\nOutput directory: {OUTPUT_DIR}/\n")

    student, djs, arxiv     = load_data()
    student_main, pre, post, trans = split_cohorts(student)
    mean_3, std_3, corr_3, inv_corr = build_reference(pre)

    thresh_05 = np.sqrt(stats.chi2.ppf(0.95, df=3))
    thresh_01 = np.sqrt(stats.chi2.ppf(0.99, df=3))
    print(f"  p=0.05 threshold: {thresh_05:.4f}σ")
    print(f"  p=0.01 threshold: {thresh_01:.4f}σ")

    m_pre  = mahal_dist(pre,   mean_3, std_3, inv_corr)
    m_post = mahal_dist(post,  mean_3, std_3, inv_corr)
    m_djs  = mahal_dist(djs,   mean_3, std_3, inv_corr)
    m_arx  = mahal_dist(arxiv, mean_3, std_3, inv_corr)

    print("\nGenerating plots...")
    plot_violin_box(student_main, OUTPUT_DIR)
    plot_mahal_histograms(student_main, mean_3, std_3, inv_corr,
                          thresh_05, thresh_01, OUTPUT_DIR)
    plot_mahal_kde(m_pre, m_post, m_djs, m_arx, thresh_05, thresh_01, OUTPUT_DIR)
    plot_scatters(pre, post, djs, arxiv, mean_3, std_3, corr_3, inv_corr,
                  thresh_05, thresh_01, OUTPUT_DIR)
    plot_metric_kde(pre, post, djs, arxiv, OUTPUT_DIR)

    print("\nRunning statistical tests...")
    run_stats(pre, post, djs, arxiv, student_main,
              mean_3, std_3, inv_corr, thresh_05, thresh_01, OUTPUT_DIR)

    print(f"\nDone. All outputs written to {OUTPUT_DIR}/")


if __name__ == '__main__':
    main()
