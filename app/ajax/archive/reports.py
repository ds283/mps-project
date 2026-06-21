#
# Created by David Seery on 08/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from flask import (
    get_template_attribute,
    current_app,
    render_template,
    url_for,
)
from flask_security import current_user
from jinja2 import Template, Environment

from ...models import SubmissionRecord, SubmissionRole
from ...models.markingevent import MarkingReport, ModeratorReport, SubmitterReport

# language=jinja2
_report = """
{% macro turnitin_chips(r) %}
    {# turnitin_outcome is a legacy Canvas LMS field not used in current Turnitin outputs; hidden from display #}
    {% if r.turnitin_score is not none %}
        <span class="small text-muted fw-semibold">Turnitin</span>
        {# 5-tier colour scale per current Turnitin documentation:
           0% = green (no match), 1-24% = blue (low), 25-49% = yellow (medium),
           50-74% = orange (high), 75-100% = red (very high) #}
        {% if r.turnitin_score == 0 %}
            {% set score_class = "text-success" %}
            {% set badge_class = "bg-success" %}
            {% set score_label = "No match" %}
        {% elif r.turnitin_score < 25 %}
            {% set score_class = "text-primary" %}
            {% set badge_class = "bg-primary" %}
            {% set score_label = "Low" %}
        {% elif r.turnitin_score < 50 %}
            {% set score_class = "text-warning" %}
            {% set badge_class = "bg-warning text-dark" %}
            {% set score_label = "Medium" %}
        {% elif r.turnitin_score < 75 %}
            {% set score_class = "" %}
            {% set badge_class = "bg-warning text-dark" %}
            {% set score_label = "High" %}
        {% else %}
            {% set score_class = "text-danger" %}
            {% set badge_class = "bg-danger" %}
            {% set score_label = "Very high" %}
        {% endif %}
        <span class="small">
            Similarity:
            <strong class="{{ score_class }}"{% if r.turnitin_score >= 50 and r.turnitin_score < 75 %} style="color: #fd7e14"{% endif %}>
                {{ r.turnitin_score }}%
            </strong>
        </span>
        <span class="badge {{ badge_class }} small">{{ score_label }}</span>
        {% if r.turnitin_web_overlap is not none %}
            <span class="small text-muted">Web: {{ r.turnitin_web_overlap }}%</span>
        {% endif %}
        {% if r.turnitin_publication_overlap is not none %}
            <span class="small text-muted">Pub: {{ r.turnitin_publication_overlap }}%</span>
        {% endif %}
        {% if r.turnitin_student_overlap is not none %}
            <span class="small text-muted">Student: {{ r.turnitin_student_overlap }}%</span>
        {% endif %}
    {% endif %}
{% endmacro %}
{% macro identity_line(parts) %}
    {% if parts|length > 0 %}
        <div class="small text-muted mt-1 d-flex flex-row flex-wrap align-items-center gap-1">
            {% for part in parts %}
                {% if not loop.first %}<span>&middot;</span>{% endif %}
                <span>{{ part }}</span>
            {% endfor %}
        </div>
    {% endif %}
{% endmacro %}
{% macro consent_badges(record) %}
    {% set avd_state = record.openday_consent_badge_state %}
    {% set ex_state = record.exemplar_consent_badge_state %}
    {% if avd_state is not none or ex_state is not none %}
        <div class="mt-1 d-flex flex-row flex-wrap align-items-center gap-2">
            {% if avd_state == 'active' %}
                <span class="badge rounded-pill badge-db-teal">
                    <i class="fas fa-graduation-cap fa-fw"></i> AVD consent active
                </span>
            {% elif avd_state == 'withdrawn' %}
                <span class="badge rounded-pill bg-warning-subtle text-warning-emphasis">
                    <i class="fas fa-exclamation-triangle fa-fw"></i> AVD consent withdrawn
                </span>
            {% elif avd_state == 'invited' %}
                <span class="small text-muted">
                    <i class="fas fa-envelope fa-fw"></i> AVD: invited, awaiting response
                </span>
            {% endif %}

            {% if ex_state == 'active' %}
                {% if record.exemplar_supervisor_approved is sameas true %}
                    {% set supervisor_word = 'approved' %}
                {% elif record.exemplar_supervisor_approved is sameas false %}
                    {% set supervisor_word = 'declined' %}
                {% else %}
                    {% set supervisor_word = 'pending' %}
                {% endif %}
                <span class="small text-muted">Exemplar: student active, supervisor {{ supervisor_word }}</span>
            {% elif ex_state == 'withdrawn' %}
                <span class="small text-muted">Exemplar: withdrawn</span>
            {% elif ex_state == 'invited' %}
                <span class="small text-muted">Exemplar: invited, awaiting response</span>
            {% endif %}
        </div>
    {% endif %}
{% endmacro %}
{% macro flags_line(record, convenor_intervention, out_of_tolerance_unassigned, ai_risk) %}
    {% if convenor_intervention or out_of_tolerance_unassigned or record.turnitin_score is not none or ai_risk is not none %}
        <div class="mt-1 d-flex flex-row flex-wrap align-items-center gap-2">
            {% if convenor_intervention %}
                <span class="badge rounded-pill bg-danger-subtle text-danger-emphasis border border-danger-subtle">
                    <i class="fas fa-exclamation-triangle fa-fw"></i> Convenor intervention
                </span>
            {% endif %}
            {% if out_of_tolerance_unassigned %}
                <span class="badge rounded-pill bg-warning-subtle text-warning-emphasis border border-warning-subtle">
                    <i class="fas fa-balance-scale fa-fw"></i> Out of tolerance &mdash; moderator not yet assigned
                </span>
            {% endif %}
            {{ turnitin_chips(record) }}
            {% if ai_risk is not none %}
                {% if ai_risk.resolved %}
                    <span class="badge rounded-pill bg-success-subtle text-success-emphasis border border-success-subtle avd-details-toggle"
                          role="button" style="cursor:pointer">
                        <i class="fas fa-robot fa-fw"></i> AI flagged &middot; resolved
                    </span>
                {% else %}
                    <span class="badge rounded-pill bg-danger-subtle text-danger-emphasis border border-danger-subtle avd-details-toggle"
                          role="button" style="cursor:pointer">
                        <i class="fas fa-robot fa-fw"></i> AI flagged
                    </span>
                {% endif %}
                {% if ai_risk.annotation %}
                    <i class="fas fa-sticky-note text-muted avd-details-toggle" role="button" style="cursor:pointer"
                       data-bs-toggle="tooltip" title="Annotation present &mdash; click to view details"></i>
                {% endif %}
            {% endif %}
        </div>
    {% endif %}
{% endmacro %}
{% macro staff_roles(roles, moderator_role_id, moderation_outcome) %}
    {% if roles|length > 0 %}
        <div class="mt-1 d-flex flex-column justify-content-start align-items-start gap-1">
            {% for role_id, group in roles|groupby('role') %}
                <div class="d-flex flex-row flex-wrap justify-content-start align-items-baseline gap-1">
                    <span class="small text-muted fw-semibold">
                        {{ group[0].role_as_str }}{{ 's' if group|length > 1 else '' }}:
                    </span>
                    {% for role in group %}
                        <span class="small">
                            <a class="text-decoration-none" href="mailto:{{ role.user.email }}">{{ role.user.name }}</a>
                        </span>
                    {% endfor %}
                    {% if role_id == moderator_role_id and moderation_outcome %}
                        <span class="small text-muted">&mdash; {{ moderation_outcome }}</span>
                    {% endif %}
                </div>
            {% endfor %}
        </div>
    {% endif %}
{% endmacro %}
{% set user = record.owner.student.user %}
<div class="d-flex flex-row gap-3 align-items-start">
    {# Thumbnail, or restriction indicator in the same slot #}
    {% if record.is_report_restricted %}
        <div style="width:64px; height:64px; border-radius:6px; border:0.5px solid var(--bs-danger-border-subtle);
                    background:var(--bs-danger-bg-subtle); display:flex; align-items:center; justify-content:center; flex-shrink:0"
             data-bs-toggle="tooltip" title="Restricted until {{ record.report_embargo.strftime("%a %d %b %Y %H:%M") }}">
            <i class="fas fa-lock fa-lg" style="color: var(--bs-danger-text-emphasis)"></i>
        </div>
    {% elif record.processed_report and record.processed_report.small_thumbnail and not record.processed_report.small_thumbnail.lost %}
        <img src="{{ url_for('documents.serve_thumbnail', asset_type='GeneratedAsset', asset_id=record.processed_report.id, size='small') }}"
             alt="Report thumbnail" width="64" height="64"
             style="object-fit: cover; border-radius: 6px; border: 0.5px solid var(--bs-border-color); flex-shrink: 0">
    {% elif record.report and record.report.small_thumbnail and not record.report.small_thumbnail.lost %}
        <img src="{{ url_for('documents.serve_thumbnail', asset_type='SubmittedAsset', asset_id=record.report_id, size='small') }}"
             alt="Report thumbnail" width="64" height="64"
             style="object-fit: cover; border-radius: 6px; border: 0.5px solid var(--bs-border-color); flex-shrink: 0">
    {% else %}
        <div style="width:64px; height:64px; border-radius:6px; border:0.5px solid var(--bs-border-color);
                    background:var(--bs-tertiary-bg); display:flex; align-items:center; justify-content:center; flex-shrink:0">
            <i class="fas fa-file-alt fa-lg" style="color: var(--bs-secondary-color)"></i>
        </div>
    {% endif %}

    <div class="flex-grow-1 bg-light p-2 rounded">
        <div class="d-flex flex-row justify-content-between align-items-start gap-2">
            <div class="flex-grow-1">
                {# Student name + project title #}
                <div class="d-flex flex-row flex-wrap justify-content-start align-items-baseline gap-2">
                    <a class="text-decoration-none fw-semibold" href="mailto:{{ user.email }}">{{ user.name }}</a>
                    {% if record.project is not none %}
                        <span class="text-muted">&middot;</span>
                        <span class="fw-semibold small">{{ record.project.name }}</span>
                    {% else %}
                        <span class="small text-muted fst-italic">No project assigned</span>
                    {% endif %}
                </div>

                {# Identity line: programme, research group, project class, year, period, grades #}
                {{ identity_line(identity_parts) }}

                {# Consent badges #}
                {{ consent_badges(record) }}

                {# Convenor intervention / out-of-tolerance / Turnitin / AI-risk flags #}
                {{ flags_line(record, convenor_intervention, out_of_tolerance_unassigned, ai_risk) }}

                {# Staff roles, generic over role type #}
                {{ staff_roles(roles, moderator_role_id, moderation_outcome) }}

                {# Expand trigger for the full marking & report details child row #}
                {% if has_details %}
                    <div class="mt-1">
                        <a href="#" class="small text-decoration-none avd-details-toggle" role="button">
                            <i class="fas fa-chevron-down fa-fw"></i> Show full marking &amp; report details
                        </a>
                    </div>
                {% endif %}
            </div>

            {# Download buttons #}
            <div class="d-flex flex-column justify-content-start align-items-end gap-1">
                {% if record.report_secret %}
                    <span class="text-danger"><i class="fas fa-exclamation-circle"></i> Report restricted</span>
                {% elif record.is_report_restricted %}
                    <span class="text-danger"><i class="fas fa-exclamation-circle"></i> Restricted until {{ record.report_embargo.strftime("%a %d %b %Y %H:%M") }}</span>
                {% else %}
                    {% if record.report is not none %}
                        <a class="btn btn-xs btn-outline-primary"
                           href="{{ url_for('admin.download_submitted_asset', asset_id=record.report_id) }}"
                           data-bs-toggle="tooltip" title="Download original report">
                            <i class="fas fa-file-download fa-fw"></i> Original
                        </a>
                    {% endif %}
                    {% if record.processed_report is not none %}
                        <a class="btn btn-xs btn-outline-secondary"
                           href="{{ url_for('admin.download_generated_asset', asset_id=record.processed_report_id) }}"
                           data-bs-toggle="tooltip" title="Download processed report">
                            <i class="fas fa-file-pdf fa-fw"></i> Processed
                        </a>
                    {% endif %}
                    {% if record.report is none and record.processed_report is none %}
                        <span class="badge bg-light text-muted border">No report</span>
                    {% endif %}
                {% endif %}
            </div>
        </div>
    </div>
</div>
"""


# language=jinja2
_details = """
{% macro stat_chip(label, value) %}
    {% if value is not none %}
        <div class="d-flex flex-column align-items-start" style="min-width:90px">
            <span class="small text-muted">{{ label }}</span>
            <span class="fw-semibold">{{ value }}</span>
        </div>
    {% endif %}
{% endmacro %}
<div class="p-3" style="background: var(--bs-tertiary-bg); border-radius: 6px; border: 1px solid var(--bs-border-color)">
    <div class="row g-4">
        <div class="col-md-6">
            {% if metrics_available %}
                <h6 class="text-uppercase small text-muted mb-2">Report statistics</h6>
                <div class="d-flex flex-row flex-wrap gap-3 mb-2">
                    {{ stat_chip("Measured words", measured_word_count) }}
                    {{ stat_chip("Appendix words", appendix_word_count) }}
                    {{ stat_chip("Pages", page_count) }}
                    {{ stat_chip("Figures", figure_count) }}
                    {{ stat_chip("Tables", table_count) }}
                </div>
                {% if stated_word_count is not none %}
                    <div class="small mb-3">
                        <span class="text-muted">Stated word count:</span> <strong>{{ stated_word_count }}</strong>
                        {% if word_count_discrepancy is not none %}
                            <span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle ms-1">
                                <i class="fas fa-exclamation-triangle fa-fw"></i>
                                {{ word_count_discrepancy.discrepancy_pct }}% difference (tolerance {{ word_count_discrepancy.tolerance_pct }}%)
                            </span>
                        {% endif %}
                    </div>
                {% endif %}
            {% endif %}

            {% if genai_status is not none %}
                <h6 class="text-uppercase small text-muted mt-2 mb-2">AI declaration</h6>
                {% if genai_status %}
                    <div class="alert alert-warning py-2 small mb-3">
                        <i class="fas fa-file-signature fa-fw me-1"></i>
                        <strong>Statement detected:</strong> {{ genai_statement }}
                    </div>
                {% else %}
                    <div class="small text-muted mb-3">No AI declaration found in report.</div>
                {% endif %}
            {% endif %}

            {% if report_summary %}
                <h6 class="text-uppercase small text-muted mt-2 mb-2">Report summary</h6>
                <p class="small mb-3">{{ report_summary }}</p>
            {% endif %}

            {% if restricted %}
                <div class="small text-muted">
                    <i class="fas fa-lock fa-fw"></i> AI declaration, report summary, and feedback documents
                    are hidden while this report is restricted.
                </div>
            {% endif %}
        </div>

        <div class="col-md-6">
            {% if rf.has_any_present %}
                <h6 class="text-uppercase small text-muted mb-2">Risk factors</h6>
                <div class="d-flex flex-column gap-2 mb-3">
                    {% for f in rf.factors %}
                        <div class="small">
                            {% if f.resolved %}
                                <span class="badge bg-success-subtle text-success-emphasis border border-success-subtle">
                                    <i class="fas fa-check-circle fa-fw"></i> {{ f.label }}
                                </span>
                                <span class="text-muted ms-1">
                                    {% if f.resolved_by_name %}resolved by {{ f.resolved_by_name }}{% else %}resolved{% endif %}
                                    {% if f.resolved_at_display %}&middot; {{ f.resolved_at_display }}{% endif %}
                                </span>
                            {% else %}
                                <span class="badge bg-danger-subtle text-danger-emphasis border border-danger-subtle">
                                    <i class="fas fa-exclamation-triangle fa-fw"></i> {{ f.label }}
                                </span>
                            {% endif %}
                            {% if f.annotation %}
                                <div class="text-muted ps-3 mt-1" style="border-left: 2px solid var(--bs-border-color)">{{ f.annotation }}</div>
                            {% endif %}
                        </div>
                    {% endfor %}
                </div>
            {% endif %}

            {% if role_reports|length > 0 %}
                <h6 class="text-uppercase small text-muted mb-2">Marking &amp; moderation reports</h6>
                <div class="d-flex flex-column gap-1 mb-3">
                    {% for rr in role_reports %}
                        <div class="small">
                            <span class="text-muted">{{ rr.label }}:</span>
                            <a href="{{ rr.url }}">{{ rr.user_name }}&rsquo;s report</a>
                        </div>
                    {% endfor %}
                </div>
            {% endif %}

            {% if feedback_links|length > 0 %}
                <h6 class="text-uppercase small text-muted mb-2">Feedback documents</h6>
                <div class="d-flex flex-row flex-wrap gap-2">
                    {% for fl in feedback_links %}
                        <a class="btn btn-xs btn-outline-primary" href="{{ fl.url }}"
                           data-bs-toggle="tooltip" title="Download feedback report">
                            <i class="fas fa-file-pdf fa-fw"></i> Download{% if feedback_links|length > 1 %} {{ loop.index }}{% endif %}
                        </a>
                    {% endfor %}
                </div>
            {% endif %}
        </div>
    </div>
</div>
"""


def _build_report_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_report)


def _build_details_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_details)


def _supervision_presentation_grades(
    record: SubmissionRecord,
) -> Tuple[Optional[float], Optional[float]]:
    """Return (supervision_grade, presentation_grade), or None for either when
    not yet graded or not applicable to this period's configuration."""
    grades = {g["label"]: g["grade"] for g in record.grade_display_data()}
    return grades.get("Supervision"), grades.get("Presentation")


def _identity_line_parts(
    record: SubmissionRecord,
    simple_label,
    supervision_grade: Optional[float],
    presentation_grade: Optional[float],
) -> List:
    """Build the ordered list of fragments for the Report panel's identity line:
    programme, research group, project class (colour badge, kept inline per the
    agreed two-column design), year, submission period, supervision grade,
    presentation grade. All plain text except the project-class badge."""
    period = record.period
    config = period.config
    programme = record.owner.student.programme
    group = record.project.group if record.project is not None else None

    parts = []
    if programme is not None:
        parts.append(programme.full_name)
    if group is not None:
        parts.append(group.name)
    parts.append(simple_label(config.project_class.make_label()))
    parts.append("{0}–{1}".format(config.year, config.year + 1))
    if period is not None:
        parts.append(period.display_name)
    parts.append("Supervision {0}".format("{:.1f}%".format(supervision_grade) if supervision_grade is not None else "—"))
    parts.append("Presentation {0}".format("{:.1f}%".format(presentation_grade) if presentation_grade is not None else "—"))
    return parts


def _latest_submitter_report(record: SubmissionRecord) -> Optional[SubmitterReport]:
    """The most recently created SubmitterReport for this record, or None if the record
    has not (yet) entered a marking workflow. A record can accumulate more than one
    SubmitterReport across re-marking events; the most recent is the one relevant to the
    dashboard's marking-history display."""
    return record.submitter_reports.order_by(SubmitterReport.creation_timestamp.desc(), SubmitterReport.id.desc()).first()


def _moderation_outcome_text(sr: Optional[SubmitterReport]) -> Optional[str]:
    """Outcome text for the moderator role-group's line, derived from the record's latest
    SubmitterReport. Returns None when there is nothing to report (tolerance never breached,
    or this is an unchosen second moderator role on a record with more than one)."""
    if sr is None:
        return None
    if sr.accepted_moderator_report_id is not None:
        return "grade accepted"
    if sr.was_moderated:
        if any(r.report_submitted for r in sr.moderator_reports):
            return "moderator report submitted, awaiting acceptance"
        return "awaiting moderator's report"
    return None


def _format_resolved_at(value: Optional[str]) -> Optional[str]:
    """Format the ISO-formatted resolved_at timestamp stored in risk_factors_data
    for display. Falls back to the raw string if it can't be parsed."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y")
    except (ValueError, TypeError):
        return value


def _ai_risk_summary(rf: Dict) -> Optional[Dict]:
    """Summarise just the AI-related risk factors (compliance statement + AI-use
    metrics) for the main row's flags line. Turnitin already has its own dedicated
    chip (turnitin_chips()); the remaining risk types (document length, similarity,
    chunking failure) are only surfaced in the full breakdown inside the details panel."""
    ai_keys = {SubmissionRecord.RISK_AI_COMPLIANCE, SubmissionRecord.RISK_AI_USE}
    ai_factors = [f for f in rf["factors"] if f["key"] in ai_keys]
    if not ai_factors:
        return None
    return {
        "resolved": all(f["resolved"] for f in ai_factors),
        "annotation": next((f["annotation"] for f in ai_factors if f.get("annotation")), None),
    }


def _role_report_links(roles: List[SubmissionRole]) -> List[Dict]:
    """For each role, the most recent MarkingReport (or ModeratorReport, for the
    moderator role) tied to that specific role, linking to the existing read-only
    (or display/edit, for moderator reports) view. Most recent by creation_timestamp
    covers roles that have accumulated more than one report across re-marking events.

    The AVD dashboard's only possible viewers are root, admin, and data_dashboard_reports
    (_can_access_avd_dashboard() — no convenor/plain-faculty branch). admin/root keep using
    the live faculty.moderator_report_form route exactly as before; a data_dashboard_reports
    viewer is routed to the read-only faculty.view_moderator_report instead, since
    moderator_report_form has a write surface that route is not widened to grant them."""
    links = []
    for role in roles:
        if role.role == SubmissionRole.ROLE_MODERATOR:
            report = role.moderator_reports.order_by(ModeratorReport.creation_timestamp.desc(), ModeratorReport.id.desc()).first()
            if report is not None:
                if current_user.has_role("admin") or current_user.has_role("root"):
                    report_url = url_for(
                        "faculty.moderator_report_form",
                        mod_report_id=report.id,
                        url=url_for("dashboards.avd_dashboard"),
                    )
                else:
                    report_url = url_for(
                        "faculty.view_moderator_report",
                        mod_report_id=report.id,
                        url=url_for("dashboards.avd_dashboard"),
                    )
                links.append(
                    {
                        "label": role.role_as_str,
                        "user_name": role.user.name,
                        "url": report_url,
                    }
                )
        else:
            report = role.marking_reports.order_by(MarkingReport.creation_timestamp.desc(), MarkingReport.id.desc()).first()
            if report is not None:
                links.append(
                    {
                        "label": role.role_as_str,
                        "user_name": role.user.name,
                        "url": url_for(
                            "faculty.view_marking_report",
                            report_id=report.id,
                            url=url_for("dashboards.avd_dashboard"),
                        ),
                    }
                )
    return links


def _feedback_links(record: SubmissionRecord) -> List[Dict]:
    """Download links for this record's generated feedback report PDFs."""
    return [{"url": url_for("admin.download_generated_asset", asset_id=fr.asset_id)} for fr in record.feedback_reports.all() if fr.asset is not None]


def _details_context(record: SubmissionRecord, roles: List[SubmissionRole]) -> Dict:
    """Build the template context for the details child-row panel: language-analysis
    metrics, AI declaration, LLM report summary, full risk-factor breakdown, staff-role
    report links, and feedback document links.

    Metrics/AI-declaration/report-summary/risk-factors are only read when
    language_analysis_complete is True (matching the existing gating convention at
    submitters_v2.html:892, since risk_factors_data is computed alongside language
    analysis and is meaningless before it has run).

    AI-declaration text, report_summary, and feedback document links are additionally
    suppressed when is_report_restricted is True (recon.md §11) — these reproduce or
    are derived from the embargoed report's actual content. Metrics, risk-factor
    presence/resolution, and staff-role report links are not suppressed: they're
    operational/processing metadata (or downstream marking output), not the report's
    content itself, and convenors still need them to manage an embargoed record.
    """
    restricted = record.is_report_restricted

    measured_word_count = appendix_word_count = page_count = None
    figure_count = table_count = stated_word_count = None
    genai_status = None
    genai_statement = None
    report_summary = None
    word_count_discrepancy = None
    rf = {"has_any_present": False, "factors": []}

    if record.language_analysis_complete:
        la = record.language_analysis_data
        metrics = la.get("metrics", {})
        llm_result = la.get("llm_result", {})

        measured_word_count = metrics.get("word_count")
        appendix_word_count = metrics.get("appendix_word_count")
        page_count = la.get("_page_count")
        figure_count = metrics.get("figure_count")
        table_count = metrics.get("table_count")

        if llm_result.get("stated_word_count_found"):
            stated_word_count = llm_result.get("stated_word_count")

        if not restricted:
            genai_status = bool(llm_result.get("genai_statement_found"))
            if genai_status:
                genai_statement = llm_result.get("genai_statement")
            report_summary = llm_result.get("report_summary") or None

        rf = record.risk_factors_ui_summary()
        for f in rf["factors"]:
            f["resolved_at_display"] = _format_resolved_at(f.get("resolved_at"))

        wcd = record.risk_factors_data.get(SubmissionRecord.RISK_WORD_COUNT_DISCREPANCY, {})
        if wcd.get("present"):
            word_count_discrepancy = {
                "discrepancy_pct": wcd.get("discrepancy_pct"),
                "tolerance_pct": wcd.get("tolerance_pct"),
            }

    metrics_available = any(v is not None for v in (measured_word_count, appendix_word_count, page_count, figure_count, table_count))

    role_reports = _role_report_links(roles)
    feedback_links = [] if restricted else _feedback_links(record)

    return {
        "metrics_available": metrics_available,
        "measured_word_count": measured_word_count,
        "appendix_word_count": appendix_word_count,
        "page_count": page_count,
        "figure_count": figure_count,
        "table_count": table_count,
        "stated_word_count": stated_word_count,
        "word_count_discrepancy": word_count_discrepancy,
        "genai_status": genai_status,
        "genai_statement": genai_statement,
        "report_summary": report_summary,
        "restricted": restricted,
        "rf": rf,
        "role_reports": role_reports,
        "feedback_links": feedback_links,
        "has_details": bool(
            metrics_available or genai_status is not None or report_summary or rf["has_any_present"] or role_reports or feedback_links or restricted
        ),
    }


def avd_dashboard_rows(records: List[SubmissionRecord]):
    """Row formatter for the AVD dashboard: one row per SubmissionRecord
    belonging to a closed SubmissionPeriodRecord. Two columns: a single rich
    "Report" panel (student, project, identity line, consent, flags, staff
    roles, downloads) and the sortable "Report grade" column."""
    simple_label = get_template_attribute("labels.html", "simple_label")

    report_templ: Template = _build_report_templ()
    details_templ: Template = _build_details_templ()

    data = []
    for record in records:
        supervision_grade, presentation_grade = _supervision_presentation_grades(record)

        report_grade = float(record.report_grade) if record.report_grade is not None else None

        roles = record.roles.all()
        has_moderator_role = any(r.role == SubmissionRole.ROLE_MODERATOR for r in roles)
        latest_sr = _latest_submitter_report(record)
        moderation_outcome = _moderation_outcome_text(latest_sr) if has_moderator_role else None
        convenor_intervention = bool(latest_sr is not None and latest_sr.convenor_intervention)
        out_of_tolerance_unassigned = bool(latest_sr is not None and latest_sr.out_of_tolerance and not has_moderator_role)

        identity_parts = _identity_line_parts(record, simple_label, supervision_grade, presentation_grade)

        details_ctx = _details_context(record, roles)
        ai_risk = _ai_risk_summary(details_ctx["rf"])

        data.append(
            {
                "report": {
                    "display": render_template(
                        report_templ,
                        record=record,
                        identity_parts=identity_parts,
                        roles=roles,
                        moderator_role_id=SubmissionRole.ROLE_MODERATOR,
                        moderation_outcome=moderation_outcome,
                        convenor_intervention=convenor_intervention,
                        out_of_tolerance_unassigned=out_of_tolerance_unassigned,
                        ai_risk=ai_risk,
                        has_details=details_ctx["has_details"],
                    ),
                    "sortstring": record.owner.student.user.last_name + record.owner.student.user.first_name,
                },
                "report_grade": {
                    "display": "{:.1f}%".format(report_grade) if report_grade is not None else "&mdash;",
                    "sortvalue": report_grade,
                },
                "details": render_template(details_templ, **details_ctx) if details_ctx["has_details"] else None,
            }
        )

    return data
