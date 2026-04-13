#
# Created by David Seery on 07/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
from bokeh.embed import components
from bokeh.models import ColumnDataSource, HoverTool, NumeralTickFormatter
from bokeh.plotting import figure
from flask import current_app, flash, redirect, request, url_for
from flask_security import current_user, login_required, roles_accepted
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    LLMOrchestrationJob,
    MainConfig,
    ProjectClass,
    ProjectClassConfig,
    SubmissionPeriodRecord,
    SubmissionRecord,
    Tenant,
)
from ..shared.context.global_context import render_template_context
from ..shared.utils import redirect_url
from ..shared.workflow_logging import log_db_commit
from ..tasks.llm_orchestration import (
    _cleanup_redis,
    _collect_error_record_ids,
    _dispatch_global_coordinator,
    is_pipeline_paused,
    launch_cycle_pipeline,
    launch_error_cycle_pipeline,
    launch_error_global_pipeline,
    launch_error_period_pipeline,
    launch_global_pipeline,
    launch_pclass_pipeline,
    launch_period_pipeline,
    set_pipeline_paused,
)
from . import dashboards

# ---------------------------------------------------------------------------
# Metric configuration (order matters — used in template iteration)
# ---------------------------------------------------------------------------

METRIC_CONFIGS = [
    {
        "key": "mattr",
        "label": "MATTR",
        "description": "Moving Average Type-Token Ratio",
        "color": "#4472C4",
        "line_color": "#2F55A4",
        "fmt": ".3f",
    },
    {
        "key": "mtld",
        "label": "MTLD",
        "description": "Measure of Textual Lexical Diversity",
        "color": "#70AD47",
        "line_color": "#4E8A2A",
        "fmt": ".1f",
    },
    {
        "key": "burstiness",
        "label": "Burstiness R",
        "description": "Goh-Barabási burstiness coefficient",
        "color": "#ED7D31",
        "line_color": "#C05A0A",
        "fmt": ".3f",
    },
    {
        "key": "sentence_cv",
        "label": "CV",
        "description": "Coefficient of variation of sentence lengths",
        "color": "#7030A0",
        "line_color": "#4D1A73",
        "fmt": ".3f",
    },
    {
        "key": "page_count",
        "label": "Pages",
        "description": "Number of pages detected in the PDF",
        "color": "#00B0F0",
        "line_color": "#007BB0",
        "fmt": ".0f",
    },
    {
        "key": "word_count",
        "label": "Words",
        "description": "Number of words detected in the report body",
        "color": "#002060",
        "line_color": "#000D33",
        "fmt": ".0f",
    },
    {
        "key": "reference_count",
        "label": "References",
        "description": "Number of bibliography entries detected",
        "color": "#375623",
        "line_color": "#1E3010",
        "fmt": ".0f",
    },
]

HISTOGRAM_THRESHOLD = 25  # minimum N to render a Bokeh histogram


# ---------------------------------------------------------------------------
# Access-control helpers
# ---------------------------------------------------------------------------


def _can_launch_orchestration(pclass: Optional[ProjectClass] = None) -> bool:
    """
    Return True if the current user may launch orchestration tasks.

    root / admin can always launch.
    Convenors can launch for pclasses they convene.
    data_dashboard_AI users cannot launch (read-only).
    """
    if current_user.has_role("root") or current_user.has_role("admin"):
        return True
    if pclass is not None and current_user.has_role("faculty"):
        fd = current_user.faculty_data
        if fd is not None:
            return pclass in fd.convenor_list
    return False


def _get_accessible_tenants() -> List[Tenant]:
    """Return the tenants the current user may view."""
    if current_user.has_role("root"):
        return db.session.query(Tenant).order_by(Tenant.name).all()
    return current_user.tenants.order_by(Tenant.name).all()


def _pclass_has_reports_subq():
    """
    Correlated EXISTS subquery: True when a ProjectClass has at least one
    SubmissionRecord (under any of its configs/periods) with a non-null report.
    Intended to be used as a filter on a query that already aliases ProjectClass.
    """
    return (
        db.session.query(SubmissionRecord.id)
        .join(
            SubmissionPeriodRecord,
            SubmissionRecord.period_id == SubmissionPeriodRecord.id,
        )
        .join(
            ProjectClassConfig,
            SubmissionPeriodRecord.config_id == ProjectClassConfig.id,
        )
        .filter(
            ProjectClassConfig.pclass_id == ProjectClass.id,
            SubmissionRecord.report_id.isnot(None),
        )
        .correlate(ProjectClass)
        .exists()
    )


def _qualifying_pclass_ids_for(candidate_ids: List[int]) -> List[int]:
    """
    Given a list of candidate ProjectClass IDs (e.g. a convenor's list),
    return those that are published and have at least one SubmissionRecord
    with a non-null report.
    """
    if not candidate_ids:
        return []
    rows = (
        db.session.query(ProjectClass.id)
        .filter(
            ProjectClass.id.in_(candidate_ids),
            ProjectClass.publish.is_(True),
        )
        .join(ProjectClassConfig, ProjectClassConfig.pclass_id == ProjectClass.id)
        .join(
            SubmissionPeriodRecord,
            SubmissionPeriodRecord.config_id == ProjectClassConfig.id,
        )
        .join(SubmissionRecord, SubmissionRecord.period_id == SubmissionPeriodRecord.id)
        .filter(SubmissionRecord.report_id.isnot(None))
        .distinct()
        .all()
    )
    return [r[0] for r in rows]


def _get_accessible_pclasses(tenant_id: Optional[int] = None) -> List[ProjectClass]:
    """
    Return the ProjectClass instances the current user may view on the dashboard.

    A project class is included only when:
      - Its ``publish`` flag is True, AND
      - It has at least one SubmissionRecord with a non-null report (i.e. there
        is actual data to display in the dashboard).
    """
    if (
        current_user.has_role("root")
        or current_user.has_role("admin")
        or current_user.has_role("data_dashboard_AI")
    ):
        q = db.session.query(ProjectClass).filter(
            ProjectClass.publish.is_(True),
            _pclass_has_reports_subq(),
        )
        if tenant_id is not None:
            q = q.filter(ProjectClass.tenant_id == tenant_id)
        return q.order_by(ProjectClass.name).all()

    # Convenors see only pclasses they convene — filtered to the qualifying subset
    if current_user.has_role("faculty") and current_user.faculty_data is not None:
        candidate_ids = [p.id for p in current_user.faculty_data.convenor_list]
        if tenant_id is not None:
            candidate_ids = [
                p.id
                for p in current_user.faculty_data.convenor_list
                if p.tenant_id == tenant_id
            ]
        qualifying_ids = set(_qualifying_pclass_ids_for(candidate_ids))
        pcls = [
            p for p in current_user.faculty_data.convenor_list if p.id in qualifying_ids
        ]
        return sorted(pcls, key=lambda p: p.name)

    return []


def _get_accessible_cycles(pclass_ids: List[int]) -> List[int]:
    """Return sorted list of academic years (MainConfig.year) that have
    SubmissionPeriodRecords containing at least one SubmissionRecord with an
    uploaded report for the given project classes."""
    rows = (
        db.session.query(ProjectClassConfig.year)
        .filter(ProjectClassConfig.pclass_id.in_(pclass_ids))
        .join(
            SubmissionPeriodRecord,
            SubmissionPeriodRecord.config_id == ProjectClassConfig.id,
        )
        .join(SubmissionRecord, SubmissionRecord.period_id == SubmissionPeriodRecord.id)
        .filter(SubmissionRecord.report_id.isnot(None))
        .distinct()
        .order_by(ProjectClassConfig.year.desc())
        .all()
    )
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _aggregate_records(records: List[SubmissionRecord]) -> Dict:
    """
    Compute descriptive statistics for a collection of SubmissionRecords.

    Returns a dict with per-metric stats (n, mean, std, min, max, q25, q75, iqr)
    plus n_total, n_missing, n_complete, n_ai_flagged.
    """
    metric_values: Dict[str, List[float]] = {
        "mattr": [],
        "mtld": [],
        "burstiness": [],
        "sentence_cv": [],
        "word_count": [],
        "reference_count": [],
        "page_count": [],
    }
    n_missing = 0
    n_stuck = 0
    n_ai_flagged = 0
    n_analysis_failed = 0
    n_feedback_failed = 0

    for record in records:
        if record.llm_analysis_failed:
            n_analysis_failed += 1
        if record.llm_feedback_failed:
            n_feedback_failed += 1

        if not record.language_analysis_complete:
            n_missing += 1
            if (
                record.language_analysis_started
                and not record.llm_analysis_failed
                and not record.llm_feedback_failed
            ):
                n_stuck += 1
            continue

        la = record.language_analysis_data
        metrics = la.get("metrics", {})

        for key in [
            "mattr",
            "mtld",
            "burstiness",
            "sentence_cv",
            "word_count",
            "reference_count",
        ]:
            val = metrics.get(key)
            if val is not None:
                try:
                    metric_values[key].append(float(val))
                except (TypeError, ValueError):
                    pass

        pc = la.get("_page_count")
        if pc is not None:
            try:
                metric_values["page_count"].append(float(pc))
            except (TypeError, ValueError):
                pass

        ai_use = record.risk_factors_data.get(record.RISK_AI_USE, {})
        if ai_use.get("present", False) and not ai_use.get("resolved", False):
            n_ai_flagged += 1

    def _stats(values: List[float]) -> Optional[Dict]:
        if not values:
            return None
        arr = np.array(values, dtype=float)
        q25, q75 = np.percentile(arr, [25, 75])
        return {
            "n": len(values),
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "q25": float(q25),
            "q75": float(q75),
            "iqr": float(q75 - q25),
            "values": values,
        }

    result = {
        "n_total": len(records),
        "n_missing": n_missing,
        "n_stuck": n_stuck,
        "n_complete": len(records) - n_missing,
        "n_ai_flagged": n_ai_flagged,
        "n_analysis_failed": n_analysis_failed,
        "n_feedback_failed": n_feedback_failed,
    }
    for key in metric_values:
        result[key] = _stats(metric_values[key])

    return result


# ---------------------------------------------------------------------------
# Bokeh histogram helpers
# ---------------------------------------------------------------------------


def _build_histogram(
    values: List[float],
    title: str,
    x_label: str,
    fill_color: str,
    line_color: str,
    bins: int = 20,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Build a Bokeh histogram for *values* and return (script, div).
    Returns (None, None) if there are fewer than HISTOGRAM_THRESHOLD values.
    """
    if len(values) < HISTOGRAM_THRESHOLD:
        return None, None

    arr = np.array(values, dtype=float)
    hist, edges = np.histogram(arr, bins=bins)

    source = ColumnDataSource(
        dict(top=hist, left=edges[:-1], right=edges[1:], count=hist)
    )

    p = figure(
        title=title,
        x_axis_label=x_label,
        y_axis_label="Count",
        width=400,
        height=240,
        toolbar_location=None,
        sizing_mode="scale_width",
    )

    p.quad(
        source=source,
        top="top",
        bottom=0,
        left="left",
        right="right",
        fill_color=fill_color,
        line_color=line_color,
        fill_alpha=0.80,
        hover_fill_alpha=1.0,
        hover_fill_color=fill_color,
    )

    p.add_tools(
        HoverTool(
            tooltips=[("Range", "@left{0.000} – @right{0.000}"), ("Count", "@count")]
        )
    )

    p.border_fill_color = None
    p.background_fill_color = "#f8f9fa"
    p.grid.grid_line_color = "white"
    p.grid.grid_line_alpha = 0.6
    p.toolbar.logo = None
    p.title.text_font_size = "11px"
    p.axis.axis_label_text_font_size = "10px"
    p.axis.major_label_text_font_size = "9px"

    script, div = components(p)
    return script, div


def _build_histograms_for_agg(
    agg: Dict,
) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    """
    Given an aggregation dict (from _aggregate_records), build Bokeh
    histograms for all metrics.  Returns a dict keyed by metric key.
    """
    result = {}
    for cfg in METRIC_CONFIGS:
        key = cfg["key"]
        metric = agg.get(key)
        if metric and metric.get("values"):
            script, div = _build_histogram(
                values=metric["values"],
                title=cfg["label"],
                x_label=cfg["description"],
                fill_color=cfg["color"],
                line_color=cfg["line_color"],
            )
        else:
            script, div = None, None
        result[key] = (script, div)
    return result


# ---------------------------------------------------------------------------
# Dashboard summary stats (for landing page card)
# ---------------------------------------------------------------------------


def _dashboard_summary_for_user() -> Dict:
    """Return counts of tenants/pclasses/cycles the current user can view."""
    tenants = _get_accessible_tenants()
    n_tenants = len(tenants)

    all_pclasses = []
    for t in tenants:
        all_pclasses.extend(_get_accessible_pclasses(t.id))
    pclass_ids = [p.id for p in all_pclasses]
    n_pclasses = len(pclass_ids)

    n_cycles = len(_get_accessible_cycles(pclass_ids)) if pclass_ids else 0

    return {"n_tenants": n_tenants, "n_pclasses": n_pclasses, "n_cycles": n_cycles}


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


@dashboards.route("/")
@login_required
def overview():
    """Landing page: a grid of cards, one per available dashboard."""
    if not (
        current_user.has_role("root")
        or current_user.has_role("admin")
        or current_user.has_role("data_dashboard_AI")
        or (
            current_user.has_role("faculty")
            and current_user.faculty_data is not None
            and current_user.faculty_data.is_convenor
        )
    ):
        flash("You do not have permission to access the dashboards.", "error")
        return redirect(url_for("home.homepage"))

    summary = _dashboard_summary_for_user()

    return render_template_context(
        "dashboards/overview.html",
        summary=summary,
    )


@dashboards.route("/ai")
@login_required
def ai_dashboard():
    """
    AI data dashboard: lexical diversity metric distributions across cohorts.
    """
    if not (
        current_user.has_role("root")
        or current_user.has_role("admin")
        or current_user.has_role("data_dashboard_AI")
        or (
            current_user.has_role("faculty")
            and current_user.faculty_data is not None
            and current_user.faculty_data.is_convenor
        )
    ):
        flash("You do not have permission to access the AI data dashboard.", "error")
        return redirect(url_for("home.homepage"))

    # ---- resolve accessible tenants ----------------------------------------
    accessible_tenants = _get_accessible_tenants()
    if not accessible_tenants:
        flash("No tenants are accessible with your current role.", "info")
        return redirect(url_for("dashboards.overview"))

    # ---- tenant filter ------------------------------------------------------
    # Single-tenant users don't get to choose; multi-tenant users do.
    if len(accessible_tenants) == 1:
        selected_tenant_id = accessible_tenants[0].id
    else:
        try:
            selected_tenant_id = int(
                request.args.get("tenant_id", accessible_tenants[0].id)
            )
        except (ValueError, TypeError):
            selected_tenant_id = accessible_tenants[0].id

    # Ensure the tenant is actually accessible
    accessible_tenant_ids = {t.id for t in accessible_tenants}
    if selected_tenant_id not in accessible_tenant_ids:
        selected_tenant_id = accessible_tenants[0].id

    selected_tenant = next(
        (t for t in accessible_tenants if t.id == selected_tenant_id), None
    )

    # ---- accessible project classes for selected tenant --------------------
    accessible_pclasses = _get_accessible_pclasses(selected_tenant_id)
    if not accessible_pclasses:
        return render_template_context(
            "dashboards/ai_dashboard.html",
            accessible_tenants=accessible_tenants,
            selected_tenant=selected_tenant,
            accessible_pclasses=[],
            selected_pclass_ids=[],
            accessible_cycles=[],
            selected_years=[],
            sort_order="desc",
            sections=[],
            active_jobs=[],
            metric_configs=METRIC_CONFIGS,
        )

    # ---- project class filter ----------------------------------------------
    all_pclass_ids = [p.id for p in accessible_pclasses]
    raw_pclass_ids = request.args.getlist("pclass_id")
    if raw_pclass_ids:
        try:
            selected_pclass_ids = [
                int(x) for x in raw_pclass_ids if int(x) in all_pclass_ids
            ]
        except (ValueError, TypeError):
            selected_pclass_ids = all_pclass_ids
    else:
        selected_pclass_ids = all_pclass_ids

    if not selected_pclass_ids:
        selected_pclass_ids = all_pclass_ids

    # ---- cycle (year) filter -----------------------------------------------
    accessible_cycles = _get_accessible_cycles(selected_pclass_ids)
    raw_years = request.args.getlist("year")
    if raw_years:
        try:
            selected_years = [int(y) for y in raw_years if int(y) in accessible_cycles]
        except (ValueError, TypeError):
            selected_years = accessible_cycles
    else:
        selected_years = accessible_cycles

    if not selected_years:
        selected_years = accessible_cycles

    # ---- sort order --------------------------------------------------------
    sort_order = request.args.get("sort_order", "desc")
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    sorted_years = sorted(selected_years, reverse=(sort_order == "desc"))

    # ---- query active orchestration jobs -----------------------------------
    active_jobs: List[LLMOrchestrationJob] = (
        db.session.query(LLMOrchestrationJob)
        .filter(LLMOrchestrationJob.status.in_(LLMOrchestrationJob.ACTIVE_STATUSES))
        .order_by(LLMOrchestrationJob.created_at.desc())
        .limit(10)
        .all()
    )

    # ---- global pause state -----------------------------------------------
    pipeline_paused: bool = is_pipeline_paused()

    # ---- rolling average: seconds per record across recent completed jobs --
    recent_completed: List[LLMOrchestrationJob] = (
        db.session.query(LLMOrchestrationJob)
        .filter(
            LLMOrchestrationJob.status == LLMOrchestrationJob.STATUS_COMPLETE,
            LLMOrchestrationJob.started_at.isnot(None),
            LLMOrchestrationJob.finished_at.isnot(None),
            LLMOrchestrationJob.total_count > 0,
        )
        .order_by(LLMOrchestrationJob.finished_at.desc())
        .limit(20)
        .all()
    )
    _total_seconds = sum(
        (j.finished_at - j.started_at).total_seconds() for j in recent_completed
    )
    _total_records = sum(
        (j.completed_count or 0) + (j.failed_count or 0) for j in recent_completed
    )
    avg_seconds_per_record: Optional[float] = (
        _total_seconds / _total_records if _total_records > 0 else None
    )

    # ---- build per-cycle sections ------------------------------------------
    # Pre-build a lookup: pclass_id → ProjectClass
    pclass_map = {p.id for p in accessible_pclasses}
    selected_pclasses = [p for p in accessible_pclasses if p.id in selected_pclass_ids]

    sections = []

    for year in sorted_years:
        cycle_records = []  # accumulate all records in this cycle
        period_subsections = []

        for pclass in selected_pclasses:
            # Find the ProjectClassConfig for this pclass and year
            config: Optional[ProjectClassConfig] = (
                db.session.query(ProjectClassConfig)
                .filter_by(pclass_id=pclass.id, year=year)
                .first()
            )
            if config is None:
                continue

            periods: List[SubmissionPeriodRecord] = config.periods.order_by(
                SubmissionPeriodRecord.submission_period
            ).all()

            for period in periods:
                records: List[SubmissionRecord] = period.submissions.filter(
                    SubmissionRecord.report_id.isnot(None)
                ).all()
                if not records:
                    continue

                agg = _aggregate_records(records)
                histograms = _build_histograms_for_agg(agg)
                can_launch = _can_launch_orchestration(pclass)

                period_subsections.append(
                    {
                        "period": period,
                        "pclass": pclass,
                        "config": config,
                        "agg": agg,
                        "histograms": histograms,
                        "can_launch": can_launch,
                    }
                )
                cycle_records.extend(records)

        if not period_subsections:
            continue

        # Cycle-level aggregate
        cycle_agg = _aggregate_records(cycle_records)
        cycle_histograms = _build_histograms_for_agg(cycle_agg)
        can_launch_cycle = current_user.has_role("root") or current_user.has_role(
            "admin"
        )

        sections.append(
            {
                "year": year,
                "label": f"{year}/{year + 1}",
                "period_subsections": period_subsections,
                "cycle_agg": cycle_agg,
                "cycle_histograms": cycle_histograms,
                "can_launch_cycle": can_launch_cycle,
            }
        )

    return render_template_context(
        "dashboards/ai_dashboard.html",
        accessible_tenants=accessible_tenants,
        selected_tenant=selected_tenant,
        accessible_pclasses=accessible_pclasses,
        selected_pclass_ids=selected_pclass_ids,
        accessible_cycles=accessible_cycles,
        selected_years=selected_years,
        sort_order=sort_order,
        sections=sections,
        active_jobs=active_jobs,
        pipeline_paused=pipeline_paused,
        avg_seconds_per_record=avg_seconds_per_record,
        metric_configs=METRIC_CONFIGS,
        histogram_threshold=HISTOGRAM_THRESHOLD,
        can_launch_global=current_user.has_role("root")
        or current_user.has_role("admin"),
    )


# ---------------------------------------------------------------------------
# Orchestration action routes (dashboard-level)
# ---------------------------------------------------------------------------


@dashboards.route("/ai/launch_period/<int:period_id>")
@roles_accepted("faculty", "admin", "root")
def launch_period(period_id: int):
    """Submit missing records for one SubmissionPeriodRecord."""
    period: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(period_id)
    pclass = period.config.project_class if period.config else None

    if not _can_launch_orchestration(pclass):
        flash(
            "You do not have permission to launch analysis tasks for this period.",
            "error",
        )
        return redirect(redirect_url())

    try:
        job = launch_period_pipeline(
            period_id=period_id, clear_existing=False, user=current_user
        )
    except Exception as exc:
        flash("An error occurred while launching the analysis pipeline.", "error")
        current_app.logger.exception(
            "LLM orchestration pipeline submission error", exc_info=exc
        )
        return redirect(redirect_url())

    if job is None:
        flash(
            "No reports are currently missing analysis results for this period.", "info"
        )
    else:
        flash(f"Queued {job.total_count} report(s) for analysis.", "success")
    return redirect(redirect_url())


@dashboards.route("/ai/clear_period/<int:period_id>")
@roles_accepted("faculty", "admin", "root")
def clear_period(period_id: int):
    """Clear and resubmit all records for one SubmissionPeriodRecord."""
    period: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(period_id)
    pclass = period.config.project_class if period.config else None

    if not _can_launch_orchestration(pclass):
        flash(
            "You do not have permission to launch analysis tasks for this period.",
            "error",
        )
        return redirect(redirect_url())

    try:
        job = launch_period_pipeline(
            period_id=period_id, clear_existing=True, user=current_user
        )
    except Exception as exc:
        flash("An error occurred while clearing and relaunching analysis.", "error")
        return redirect(redirect_url())

    if job is None:
        flash("No reports with uploaded files were found for this period.", "info")
    else:
        flash(
            f"Cleared existing results and queued {job.total_count} report(s) for re-analysis.",
            "success",
        )
    return redirect(redirect_url())


@dashboards.route("/ai/launch_pclass/<int:config_id>")
@roles_accepted("faculty", "admin", "root")
def launch_pclass(config_id: int):
    """Submit missing records for one ProjectClassConfig."""
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(config_id)

    if not _can_launch_orchestration(config.project_class):
        flash(
            "You do not have permission to launch analysis tasks for this project class.",
            "error",
        )
        return redirect(redirect_url())

    try:
        job = launch_pclass_pipeline(
            pclass_config_id=config_id, clear_existing=False, user=current_user
        )
    except Exception as exc:
        flash("An error occurred while launching the analysis pipeline.", "error")
        current_app.logger.exception(
            "LLM orchestration pipeline submission error", exc_info=exc
        )
        return redirect(redirect_url())

    if job is None:
        flash("No reports are currently missing analysis results.", "info")
    else:
        flash(f"Queued {job.total_count} report(s) for analysis.", "success")
    return redirect(redirect_url())


@dashboards.route("/ai/clear_pclass/<int:config_id>")
@roles_accepted("faculty", "admin", "root")
def clear_pclass(config_id: int):
    """Clear and resubmit all records for one ProjectClassConfig."""
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(config_id)

    if not _can_launch_orchestration(config.project_class):
        flash(
            "You do not have permission to launch analysis tasks for this project class.",
            "error",
        )
        return redirect(redirect_url())

    try:
        job = launch_pclass_pipeline(
            pclass_config_id=config_id, clear_existing=True, user=current_user
        )
    except Exception as exc:
        flash("An error occurred while clearing and relaunching analysis.", "error")
        return redirect(redirect_url())

    if job is None:
        flash("No reports with uploaded files were found.", "info")
    else:
        flash(
            f"Cleared existing results and queued {job.total_count} report(s) for re-analysis.",
            "success",
        )
    return redirect(redirect_url())


@dashboards.route("/ai/launch_cycle/<int:year>")
@roles_accepted("admin", "root")
def launch_cycle(year: int):
    """Submit missing records for an entire academic cycle."""
    try:
        job = launch_cycle_pipeline(year=year, clear_existing=False, user=current_user)
    except Exception as exc:
        flash("An error occurred while launching the analysis pipeline.", "error")
        current_app.logger.exception(
            "LLM orchestration pipeline submission error", exc_info=exc
        )
        return redirect(redirect_url())

    if job is None:
        flash(
            "No reports are currently missing analysis results for this cycle.", "info"
        )
    else:
        flash(f"Queued {job.total_count} report(s) for analysis.", "success")
    return redirect(redirect_url())


@dashboards.route("/ai/clear_cycle/<int:year>")
@roles_accepted("admin", "root")
def clear_cycle(year: int):
    """Clear and resubmit all records for an entire academic cycle."""
    try:
        job = launch_cycle_pipeline(year=year, clear_existing=True, user=current_user)
    except Exception as exc:
        flash("An error occurred while clearing and relaunching analysis.", "error")
        return redirect(redirect_url())

    if job is None:
        flash("No reports with uploaded files were found for this cycle.", "info")
    else:
        flash(
            f"Cleared existing results and queued {job.total_count} report(s) for re-analysis.",
            "success",
        )
    return redirect(redirect_url())


@dashboards.route("/ai/launch_global")
@roles_accepted("admin", "root")
def launch_global():
    """Submit all missing records globally."""
    try:
        job = launch_global_pipeline(clear_existing=False, user=current_user)
    except Exception as exc:
        flash("An error occurred while launching the analysis pipeline.", "error")
        current_app.logger.exception(
            "LLM orchestration pipeline submission error", exc_info=exc
        )
        return redirect(redirect_url())

    if job is None:
        flash("No reports are currently missing analysis results.", "info")
    else:
        flash(f"Queued {job.total_count} report(s) for analysis.", "success")
    return redirect(redirect_url())


@dashboards.route("/ai/clear_global")
@roles_accepted("admin", "root")
def clear_global():
    """Clear and resubmit every report in the database."""
    try:
        job = launch_global_pipeline(clear_existing=True, user=current_user)
    except Exception as exc:
        flash("An error occurred while clearing and relaunching analysis.", "error")
        return redirect(redirect_url())

    if job is None:
        flash("No reports with uploaded files were found.", "info")
    else:
        flash(
            f"Cleared existing results and queued {job.total_count} report(s) for re-analysis.",
            "success",
        )
    return redirect(redirect_url())


# ---------------------------------------------------------------------------
# Error-flag management routes  (clear only / clear + resubmit)
# ---------------------------------------------------------------------------


def _clear_error_flags_for_records(record_ids: List[int]) -> int:
    """
    Clear LLM error flags on the given SubmissionRecord IDs in a single bulk
    UPDATE.  Returns the number of rows updated.  Does NOT commit.
    """
    if not record_ids:
        return 0
    count = (
        db.session.query(SubmissionRecord)
        .filter(SubmissionRecord.id.in_(record_ids))
        .update(
            {
                SubmissionRecord.language_analysis_started: False,
                SubmissionRecord.llm_analysis_failed: False,
                SubmissionRecord.llm_failure_reason: None,
                SubmissionRecord.llm_feedback_failed: None,
                SubmissionRecord.llm_feedback_failure_reason: None,
            },
            synchronize_session="fetch",
        )
    )
    return count


@dashboards.route("/ai/clear_errors_period/<int:period_id>")
@roles_accepted("faculty", "admin", "root")
def clear_errors_period(period_id: int):
    """Clear LLM error flags for records in one SubmissionPeriodRecord (no resubmit)."""
    period: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(period_id)
    pclass = period.config.project_class if period.config else None

    if not _can_launch_orchestration(pclass):
        flash("You do not have permission to manage analysis tasks for this period.", "error")
        return redirect(redirect_url())

    record_ids = _collect_error_record_ids([period_id])
    if not record_ids:
        flash("No records with error flags were found for this period.", "info")
        return redirect(redirect_url())

    count = _clear_error_flags_for_records(record_ids)
    try:
        log_db_commit(
            f"Cleared LLM error flags on {count} record(s) for period #{period_id} (no resubmit)"
        )
    except SQLAlchemyError:
        db.session.rollback()
        flash("An error occurred while clearing error flags.", "error")
        return redirect(redirect_url())

    flash(f"Cleared error flags on {count} record(s). Use 'Submit missing' to requeue.", "success")
    return redirect(redirect_url())


@dashboards.route("/ai/resubmit_errors_period/<int:period_id>")
@roles_accepted("faculty", "admin", "root")
def resubmit_errors_period(period_id: int):
    """Clear error records and resubmit them for one SubmissionPeriodRecord."""
    period: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(period_id)
    pclass = period.config.project_class if period.config else None

    if not _can_launch_orchestration(pclass):
        flash("You do not have permission to launch analysis tasks for this period.", "error")
        return redirect(redirect_url())

    try:
        job = launch_error_period_pipeline(period_id=period_id, user=current_user)
    except Exception as exc:
        flash("An error occurred while launching re-analysis for error records.", "error")
        current_app.logger.exception("LLM error resubmit failed", exc_info=exc)
        return redirect(redirect_url())

    if job is None:
        flash("No records with error flags were found for this period.", "info")
    else:
        flash(f"Cleared and queued {job.total_count} error record(s) for re-analysis.", "success")
    return redirect(redirect_url())


@dashboards.route("/ai/clear_errors_cycle/<int:year>")
@roles_accepted("admin", "root")
def clear_errors_cycle(year: int):
    """Clear LLM error flags for an entire academic cycle (no resubmit)."""
    period_ids = [
        row[0]
        for row in db.session.query(SubmissionPeriodRecord.id)
        .join(ProjectClassConfig, ProjectClassConfig.id == SubmissionPeriodRecord.config_id)
        .filter(ProjectClassConfig.year == year)
        .all()
    ]
    record_ids = _collect_error_record_ids(period_ids) if period_ids else []
    if not record_ids:
        flash("No records with error flags were found for this cycle.", "info")
        return redirect(redirect_url())

    count = _clear_error_flags_for_records(record_ids)
    try:
        log_db_commit(f"Cleared LLM error flags on {count} record(s) for cycle {year} (no resubmit)")
    except SQLAlchemyError:
        db.session.rollback()
        flash("An error occurred while clearing error flags.", "error")
        return redirect(redirect_url())

    flash(f"Cleared error flags on {count} record(s). Use 'Submit missing' to requeue.", "success")
    return redirect(redirect_url())


@dashboards.route("/ai/resubmit_errors_cycle/<int:year>")
@roles_accepted("admin", "root")
def resubmit_errors_cycle(year: int):
    """Clear error records and resubmit them for an entire academic cycle."""
    try:
        job = launch_error_cycle_pipeline(year=year, user=current_user)
    except Exception as exc:
        flash("An error occurred while launching re-analysis for error records.", "error")
        current_app.logger.exception("LLM error resubmit failed", exc_info=exc)
        return redirect(redirect_url())

    if job is None:
        flash("No records with error flags were found for this cycle.", "info")
    else:
        flash(f"Cleared and queued {job.total_count} error record(s) for re-analysis.", "success")
    return redirect(redirect_url())


@dashboards.route("/ai/clear_errors_global")
@roles_accepted("admin", "root")
def clear_errors_global():
    """Clear LLM error flags globally (no resubmit)."""
    period_ids = [row[0] for row in db.session.query(SubmissionPeriodRecord.id).all()]
    record_ids = _collect_error_record_ids(period_ids) if period_ids else []
    if not record_ids:
        flash("No records with error flags were found.", "info")
        return redirect(redirect_url())

    count = _clear_error_flags_for_records(record_ids)
    try:
        log_db_commit(f"Cleared LLM error flags on {count} record(s) globally (no resubmit)")
    except SQLAlchemyError:
        db.session.rollback()
        flash("An error occurred while clearing error flags.", "error")
        return redirect(redirect_url())

    flash(f"Cleared error flags on {count} record(s). Use 'Submit missing' to requeue.", "success")
    return redirect(redirect_url())


@dashboards.route("/ai/resubmit_errors_global")
@roles_accepted("admin", "root")
def resubmit_errors_global():
    """Clear all error records globally and resubmit them."""
    try:
        job = launch_error_global_pipeline(user=current_user)
    except Exception as exc:
        flash("An error occurred while launching re-analysis for error records.", "error")
        current_app.logger.exception("LLM error resubmit failed", exc_info=exc)
        return redirect(redirect_url())

    if job is None:
        flash("No records with error flags were found.", "info")
    else:
        flash(f"Cleared and queued {job.total_count} error record(s) for re-analysis.", "success")
    return redirect(redirect_url())


# ---------------------------------------------------------------------------
# AJAX endpoint — queue status polling
# ---------------------------------------------------------------------------


@dashboards.route("/ai/active_jobs_status")
@login_required
def active_jobs_status():
    """
    Return a JSON payload for the auto-reload poller.

    Accepts an optional ``ids`` query parameter: a comma-separated list of
    LLMOrchestrationJob UUIDs that were active when the page was rendered.
    ``just_finished`` is True if any of those watched jobs have now reached a
    terminal state.  Detection is timestamp-free — there is no window that can
    expire.

    ``active_count`` is the current count of active jobs, used by the client
    to detect new jobs that appeared after the page was loaded.

    ``jobs`` maps each still-active watched UUID to its current progress
    counters, allowing the client to update the table cells in-place without
    a full page reload.
    """
    from flask import jsonify

    raw_ids = request.args.get("ids", "")
    watched_uuids = [uid.strip() for uid in raw_ids.split(",") if uid.strip()]

    now = datetime.now()
    jobs_data: Dict[str, dict] = {}

    if watched_uuids:
        finished_count = (
            db.session.query(LLMOrchestrationJob)
            .filter(
                LLMOrchestrationJob.uuid.in_(watched_uuids),
                LLMOrchestrationJob.status.in_(
                    [LLMOrchestrationJob.STATUS_COMPLETE, LLMOrchestrationJob.STATUS_FAILED]
                ),
            )
            .count()
        )
        # Fetch live progress for each still-active watched job
        active_watched = (
            db.session.query(LLMOrchestrationJob)
            .filter(
                LLMOrchestrationJob.uuid.in_(watched_uuids),
                LLMOrchestrationJob.status.in_(LLMOrchestrationJob.ACTIVE_STATUSES),
            )
            .all()
        )
        for job in active_watched:
            elapsed = (
                (now - job.started_at).total_seconds() if job.started_at is not None else None
            )
            jobs_data[job.uuid] = {
                "completed": job.completed_count or 0,
                "failed": job.failed_count or 0,
                "total": job.total_count or 0,
                "elapsed_seconds": elapsed,
            }
    else:
        finished_count = 0

    active_count = (
        db.session.query(LLMOrchestrationJob)
        .filter(LLMOrchestrationJob.status.in_(LLMOrchestrationJob.ACTIVE_STATUSES))
        .count()
    )

    return jsonify(
        {"just_finished": finished_count > 0, "active_count": active_count, "jobs": jobs_data}
    )


# ---------------------------------------------------------------------------
# Pipeline pause / resume routes
# ---------------------------------------------------------------------------


@dashboards.route("/ai/pause_pipeline")
@roles_accepted("admin", "root")
def pause_pipeline():
    """Globally pause the analysis pipeline (no new records dispatched)."""
    try:
        set_pipeline_paused(True)
    except Exception as exc:
        current_app.logger.exception("pause_pipeline: could not set pause flag", exc_info=exc)
        flash("Could not pause the pipeline — Redis may be unavailable.", "error")
        return redirect(redirect_url())
    flash(
        "Analysis pipeline paused. Records currently in-flight will complete normally; "
        "no new records will be dispatched until the pipeline is resumed.",
        "success",
    )
    return redirect(redirect_url())


@dashboards.route("/ai/resume_pipeline")
@roles_accepted("admin", "root")
def resume_pipeline():
    """Clear the global pipeline pause flag and re-trigger the coordinator."""
    try:
        set_pipeline_paused(False)
    except Exception as exc:
        current_app.logger.exception("resume_pipeline: could not clear pause flag", exc_info=exc)
        flash("Could not resume the pipeline — Redis may be unavailable.", "error")
        return redirect(redirect_url())
    try:
        _dispatch_global_coordinator()
    except Exception as exc:
        current_app.logger.warning(
            f"resume_pipeline: could not dispatch coordinator after resume: {exc}"
        )
    flash("Analysis pipeline resumed.", "success")
    return redirect(redirect_url())


@dashboards.route("/ai/pause_job/<uuid>")
@roles_accepted("faculty", "admin", "root")
def pause_job(uuid: str):
    """Pause a single LLMOrchestrationJob (owner or root/admin only)."""
    job: LLMOrchestrationJob = (
        db.session.query(LLMOrchestrationJob).filter_by(uuid=uuid).first_or_404()
    )
    if not (
        current_user.has_role("root")
        or current_user.has_role("admin")
        or (job.owner_id is not None and job.owner_id == current_user.id)
    ):
        flash("You do not have permission to pause this job.", "error")
        return redirect(redirect_url())
    if not job.is_active:
        flash("This job has already finished.", "info")
        return redirect(redirect_url())
    job.pause()
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("pause_job: SQLAlchemyError", exc_info=exc)
        flash("Could not pause the job — please try again.", "error")
        return redirect(redirect_url())
    flash(
        "Job paused. Records currently in-flight will complete; "
        "no further records from this job will be dispatched until it is resumed.",
        "success",
    )
    return redirect(redirect_url())


@dashboards.route("/ai/resume_job/<uuid>")
@roles_accepted("faculty", "admin", "root")
def resume_job(uuid: str):
    """Resume a paused LLMOrchestrationJob (owner or root/admin only)."""
    job: LLMOrchestrationJob = (
        db.session.query(LLMOrchestrationJob).filter_by(uuid=uuid).first_or_404()
    )
    if not (
        current_user.has_role("root")
        or current_user.has_role("admin")
        or (job.owner_id is not None and job.owner_id == current_user.id)
    ):
        flash("You do not have permission to resume this job.", "error")
        return redirect(redirect_url())
    if not job.is_active:
        flash("This job has already finished.", "info")
        return redirect(redirect_url())
    job.resume()
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("resume_job: SQLAlchemyError", exc_info=exc)
        flash("Could not resume the job — please try again.", "error")
        return redirect(redirect_url())
    try:
        _dispatch_global_coordinator()
    except Exception as exc:
        current_app.logger.warning(
            f"resume_job: could not dispatch coordinator after resume: {exc}"
        )
    flash("Job resumed.", "success")
    return redirect(redirect_url())


@dashboards.route("/ai/cancel_job/<uuid>")
@roles_accepted("faculty", "admin", "root")
def cancel_job(uuid: str):
    """Cancel a single LLMOrchestrationJob (owner or root/admin only).

    Sets STATUS_FAILED immediately and deletes both Redis queue keys so no
    further records are dispatched.  In-flight records complete normally —
    their done/error callbacks increment counters but the job is already
    terminal so no further dispatch occurs.
    """
    job: LLMOrchestrationJob = (
        db.session.query(LLMOrchestrationJob).filter_by(uuid=uuid).first_or_404()
    )
    if not (
        current_user.has_role("root")
        or current_user.has_role("admin")
        or (job.owner_id is not None and job.owner_id == current_user.id)
    ):
        flash("You do not have permission to cancel this job.", "error")
        return redirect(redirect_url())
    if not job.is_active:
        flash("This job has already finished.", "info")
        return redirect(redirect_url())
    job.mark_failed()
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("cancel_job: SQLAlchemyError", exc_info=exc)
        flash("Could not cancel the job — please try again.", "error")
        return redirect(redirect_url())
    _cleanup_redis(job)
    flash(
        "Job cancelled. Queued records have been discarded; "
        "any in-flight records will complete harmlessly.",
        "success",
    )
    return redirect(redirect_url())


@dashboards.route("/ai/cancel_pipeline")
@roles_accepted("admin", "root")
def cancel_pipeline():
    """Cancel all active LLMOrchestrationJobs globally (admin/root only).

    Marks every PENDING/RUNNING job as FAILED and deletes their Redis queues.
    In-flight records continue to completion; queued records are discarded.
    """
    active_jobs = (
        db.session.query(LLMOrchestrationJob)
        .filter(LLMOrchestrationJob.status.in_(LLMOrchestrationJob.ACTIVE_STATUSES))
        .all()
    )
    if not active_jobs:
        flash("No active jobs to cancel.", "info")
        return redirect(redirect_url())
    for job in active_jobs:
        job.mark_failed()
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        current_app.logger.exception("cancel_pipeline: SQLAlchemyError", exc_info=exc)
        flash("Could not cancel the pipeline — please try again.", "error")
        return redirect(redirect_url())
    for job in active_jobs:
        _cleanup_redis(job)
    n = len(active_jobs)
    flash(
        f"Pipeline cancelled: {n} job{'s' if n != 1 else ''} terminated. "
        "Any in-flight records will complete harmlessly.",
        "success",
    )
    return redirect(redirect_url())


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------


def _record_ids_for_period(period_id: int) -> List[int]:
    return [
        r[0]
        for r in db.session.query(SubmissionRecord.id)
        .filter(
            SubmissionRecord.period_id == period_id,
            SubmissionRecord.report_id.isnot(None),
        )
        .all()
    ]


def _record_ids_for_pclass_config(config_id: int) -> List[int]:
    period_ids = [
        r[0]
        for r in db.session.query(SubmissionPeriodRecord.id)
        .filter(SubmissionPeriodRecord.config_id == config_id)
        .all()
    ]
    if not period_ids:
        return []
    return [
        r[0]
        for r in db.session.query(SubmissionRecord.id)
        .filter(
            SubmissionRecord.period_id.in_(period_ids),
            SubmissionRecord.report_id.isnot(None),
        )
        .all()
    ]


def _record_ids_for_cycle(year: int, pclass_ids: Optional[List[int]] = None) -> List[int]:
    q = (
        db.session.query(SubmissionPeriodRecord.id)
        .join(
            ProjectClassConfig,
            ProjectClassConfig.id == SubmissionPeriodRecord.config_id,
        )
        .filter(ProjectClassConfig.year == year)
    )
    if pclass_ids:
        q = q.filter(ProjectClassConfig.pclass_id.in_(pclass_ids))
    period_ids = [r[0] for r in q.all()]
    if not period_ids:
        return []
    return [
        r[0]
        for r in db.session.query(SubmissionRecord.id)
        .filter(
            SubmissionRecord.period_id.in_(period_ids),
            SubmissionRecord.report_id.isnot(None),
        )
        .all()
    ]


def _record_ids_global(
    pclass_ids: Optional[List[int]] = None, years: Optional[List[int]] = None
) -> List[int]:
    if pclass_ids or years:
        q = (
            db.session.query(SubmissionRecord.id)
            .join(
                SubmissionPeriodRecord,
                SubmissionPeriodRecord.id == SubmissionRecord.period_id,
            )
            .join(
                ProjectClassConfig,
                ProjectClassConfig.id == SubmissionPeriodRecord.config_id,
            )
            .filter(SubmissionRecord.report_id.isnot(None))
        )
        if pclass_ids:
            q = q.filter(ProjectClassConfig.pclass_id.in_(pclass_ids))
        if years:
            q = q.filter(ProjectClassConfig.year.in_(years))
        return [r[0] for r in q.all()]
    return [
        r[0]
        for r in db.session.query(SubmissionRecord.id)
        .filter(SubmissionRecord.report_id.isnot(None))
        .all()
    ]


def _dispatch_export(
    fmt: str, record_ids: List[int], filename_stem: str, description: str
) -> bool:
    """
    Dispatch the appropriate export Celery task.
    Returns True if dispatched, False if no records or unknown format.
    """
    if not record_ids:
        return False
    celery = current_app.extensions["celery"]
    task_name = (
        "app.tasks.ai_dashboard_export.export_ai_dashboard_xlsx"
        if fmt == "xlsx"
        else "app.tasks.ai_dashboard_export.export_ai_dashboard_csv"
    )
    task = celery.tasks[task_name]
    task.apply_async(
        args=[current_user.id, record_ids, filename_stem, description],
        queue="default",
    )
    return True


# ---------------------------------------------------------------------------
# Export trigger routes
# ---------------------------------------------------------------------------


@dashboards.route("/ai/export/period/<int:period_id>")
@login_required
def export_period(period_id: int):
    """Queue an export of all records for one SubmissionPeriodRecord."""
    fmt = request.args.get("fmt", "xlsx")
    period: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(period_id)
    pclass = period.config.project_class if period.config else None

    if not (
        _can_launch_orchestration(pclass) or current_user.has_role("data_dashboard_AI")
    ):
        flash("You do not have permission to export this data.", "error")
        return redirect(redirect_url())

    record_ids = _record_ids_for_period(period_id)
    stem = f"AI_Dashboard_{period.display_name.replace(' ', '_')}"
    desc = f"AI dashboard export — {period.display_name}"
    if _dispatch_export(fmt, record_ids, stem, desc):
        flash(
            "Export queued. You will be notified in your Download Centre when it is ready.",
            "success",
        )
    else:
        flash("No records found for this period.", "info")
    return redirect(redirect_url())


@dashboards.route("/ai/export/pclass/<int:config_id>")
@login_required
def export_pclass(config_id: int):
    """Queue an export of all records for one ProjectClassConfig."""
    fmt = request.args.get("fmt", "xlsx")
    config: ProjectClassConfig = ProjectClassConfig.query.get_or_404(config_id)

    if not (
        _can_launch_orchestration(config.project_class)
        or current_user.has_role("data_dashboard_AI")
    ):
        flash("You do not have permission to export this data.", "error")
        return redirect(redirect_url())

    pclass_abbr = (
        config.project_class.abbreviation if config.project_class else str(config_id)
    )
    record_ids = _record_ids_for_pclass_config(config_id)
    stem = f"AI_Dashboard_{pclass_abbr}_{config.year}"
    desc = f"AI dashboard export — {pclass_abbr} {config.year}/{config.year + 1}"
    if _dispatch_export(fmt, record_ids, stem, desc):
        flash(
            "Export queued. You will be notified in your Download Centre when it is ready.",
            "success",
        )
    else:
        flash("No records found for this project class.", "info")
    return redirect(redirect_url())


@dashboards.route("/ai/export/cycle/<int:year>")
@login_required
def export_cycle(year: int):
    """Queue an export of all records for an academic cycle."""
    fmt = request.args.get("fmt", "xlsx")

    if not (
        current_user.has_role("root")
        or current_user.has_role("admin")
        or current_user.has_role("data_dashboard_AI")
    ):
        flash("You do not have permission to export cycle-level data.", "error")
        return redirect(redirect_url())

    try:
        pclass_ids = [int(x) for x in request.args.getlist("pclass_id")] or None
    except (ValueError, TypeError):
        pclass_ids = None

    record_ids = _record_ids_for_cycle(year, pclass_ids=pclass_ids)
    stem = f"AI_Dashboard_Cycle_{year}"
    desc = f"AI dashboard export — cycle {year}/{year + 1}"
    if _dispatch_export(fmt, record_ids, stem, desc):
        flash(
            "Export queued. You will be notified in your Download Centre when it is ready.",
            "success",
        )
    else:
        flash("No records found for this cycle.", "info")
    return redirect(redirect_url())


@dashboards.route("/ai/export/global")
@roles_accepted("admin", "root", "data_dashboard_AI")
def export_global():
    """Queue a global export of all records."""
    fmt = request.args.get("fmt", "xlsx")

    try:
        pclass_ids = [int(x) for x in request.args.getlist("pclass_id")] or None
    except (ValueError, TypeError):
        pclass_ids = None

    try:
        years = [int(x) for x in request.args.getlist("year")] or None
    except (ValueError, TypeError):
        years = None

    record_ids = _record_ids_global(pclass_ids=pclass_ids, years=years)
    stem = "AI_Dashboard_Global"
    desc = "AI dashboard export — all records"
    if _dispatch_export(fmt, record_ids, stem, desc):
        flash(
            "Export queued. You will be notified in your Download Centre when it is ready.",
            "success",
        )
    else:
        flash("No records found.", "info")
    return redirect(redirect_url())
