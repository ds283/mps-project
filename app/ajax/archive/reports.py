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

# Priority order for role groups in the staff block. Roles not in this map sort after all listed
# types, preserving generic iteration for unlisted role types (Exam board, External examiner, etc.).
_ROLE_PRIORITY: Dict[int, int] = {
    SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR: 0,
    SubmissionRole.ROLE_SUPERVISOR: 1,
    SubmissionRole.ROLE_MARKER: 2,
    SubmissionRole.ROLE_PRESENTATION_ASSESSOR: 3,
    SubmissionRole.ROLE_MODERATOR: 4,
}
_ROLE_PRIORITY_DEFAULT: int = len(_ROLE_PRIORITY)

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
{% macro staff_roles(grouped_roles, role_report_urls, moderator_role_id, moderation_outcome) %}
    {# Local label override: ROLE_PRESENTATION_ASSESSOR (2) uses 'Presentation assessor' here rather than
       the global role_as_str value 'Assessor', which is correct for all other contexts in the application. #}
    {% set _local_labels = {2: 'Presentation assessor'} %}
    {% if grouped_roles|length > 0 %}
        <div class="mt-2" style="background: var(--bs-tertiary-bg); border: 1px solid var(--bs-border-color); border-radius: 6px; padding: 6px 10px">
            <div style="font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--bs-secondary-color); margin-bottom: 4px">Staff</div>
            <div class="d-flex flex-column gap-1">
                {% for role_type, group in grouped_roles %}
                    <div class="d-flex flex-row flex-wrap justify-content-start align-items-baseline gap-1">
                        <span class="small text-muted fw-semibold">
                            {{ _local_labels.get(role_type, group[0].role_as_str) }}{{ 's' if group|length > 1 else '' }}:
                        </span>
                        {% for role in group %}
                            {% set report_url = role_report_urls.get(role.id) %}
                            <span class="small">
                                {% if report_url %}
                                    <a class="text-decoration-none" href="{{ report_url }}">{{ role.user.name }}</a>
                                {% else %}
                                    {{ role.user.name }}
                                {% endif %}
                            </span>
                            {% if not loop.last %}<span class="text-muted small">,</span>{% endif %}
                        {% endfor %}
                        {% if role_type == moderator_role_id and moderation_outcome %}
                            <span class="small text-muted">&mdash; {{ moderation_outcome }}</span>
                        {% endif %}
                    </div>
                {% endfor %}
            </div>
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

                {# Staff roles: visually contained, priority-ordered, role names link to their reports #}
                {{ staff_roles(grouped_roles, role_report_urls, moderator_role_id, moderation_outcome) }}
            </div>

            {# Download button: processed report preferred; original triggers an unprocessed-warning modal #}
            <div class="d-flex flex-column justify-content-start align-items-end gap-1">
                {% if record.report_secret %}
                    <span class="text-danger"><i class="fas fa-exclamation-circle"></i> Report restricted</span>
                {% elif record.is_report_restricted %}
                    <span class="text-danger"><i class="fas fa-exclamation-circle"></i> Restricted until {{ record.report_embargo.strftime("%a %d %b %Y %H:%M") }}</span>
                {% elif record.processed_report is not none %}
                    <a class="btn btn-xs btn-outline-secondary"
                       href="{{ url_for('admin.download_generated_asset', asset_id=record.processed_report_id) }}"
                       data-bs-toggle="tooltip" title="Download report">
                        <i class="fas fa-file-pdf fa-fw"></i> Download report
                    </a>
                {% elif record.report is not none %}
                    <button class="btn btn-xs btn-outline-secondary"
                            data-bs-toggle="modal"
                            data-bs-target="#avdUnprocessedReportModal"
                            data-download-url="{{ url_for('admin.download_submitted_asset', asset_id=record.report_id) }}"
                            title="Download report (unprocessed)">
                        <i class="fas fa-file-download fa-fw"></i> Download report
                    </button>
                {% else %}
                    <span class="badge bg-light text-muted border">No report</span>
                {% endif %}
            </div>
        </div>

        {# Full-width expand/collapse footer bar #}
        {% if has_details %}
            <div class="avd-details-toggle avd-footer-toggle mt-2 pt-2 text-center"
                 role="button"
                 style="cursor: pointer; border-top: 1px solid var(--bs-border-color)">
                <span class="avd-toggle-icon small text-muted"><i class="fas fa-chevron-down fa-fw"></i></span>
                <span class="avd-toggle-label small text-muted ms-1">Show full marking &amp; report details</span>
            </div>
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_details = """
{% macro metric_tile(value, label, variant='secondary', denominator=none, zero_variant=none, nonzero_variant=none, value_ok=none) %}
    {# Inlined from convenor/dashboard/overview_cards/_metric_tile.html —
       string templates compiled with env.from_string() share the app environment but inlining avoids
       any loader-path uncertainty at render time. #}
    {% if value_ok is not none %}
        {% set resolved = zero_variant if value_ok else nonzero_variant %}
    {% elif zero_variant is not none and nonzero_variant is not none %}
        {% set resolved = zero_variant if value == 0 else nonzero_variant %}
    {% else %}
        {% set resolved = variant %}
    {% endif %}
    {% if resolved == 'secondary' %}
        {% set bg_token = 'var(--bs-secondary-bg)' %}
        {% set border_token = 'var(--bs-border-color)' %}
    {% else %}
        {% set bg_token = 'var(--bs-' ~ resolved ~ '-bg-subtle)' %}
        {% set border_token = 'var(--bs-' ~ resolved ~ '-border-subtle)' %}
    {% endif %}
    <div class="rounded p-1 text-center"
         style="background: {{ bg_token }}; border: 1px solid {{ border_token }}">
        {% if resolved == 'secondary' %}
            <div class="small fw-bold text-body-secondary">
                {{ value }}{% if denominator is not none %}<small class="fw-normal text-body-secondary">/{{ denominator }}</small>{% endif %}
            </div>
        {% else %}
            <div class="small fw-bold" style="color: var(--bs-{{ resolved }}-text-emphasis)">
                {{ value }}{% if denominator is not none %}<small class="fw-normal text-body-secondary">/{{ denominator }}</small>{% endif %}
            </div>
        {% endif %}
        <div class="text-body-secondary" style="font-size:10px">{{ label }}</div>
    </div>
{% endmacro %}
<div class="p-3">

    {# Report summary callout — promoted to the top of the details panel #}
    {% if report_summary %}
        <div class="mb-3 p-3 rounded" style="background: var(--bs-info-bg-subtle); border: 1px solid var(--bs-info-border-subtle)">
            <div class="small fw-semibold mb-1" style="color: var(--bs-info-text-emphasis)">
                <i class="fas fa-robot fa-fw"></i> AI report summary
            </div>
            <p class="small mb-0" style="color: var(--bs-body-color)">{{ report_summary }}</p>
        </div>
    {% endif %}

    {% if restricted %}
        <div class="small text-muted mb-3">
            <i class="fas fa-lock fa-fw"></i> AI declaration, report summary, and feedback documents
            are hidden while this report is restricted.
        </div>
    {% endif %}

    <div class="row g-4">
        <div class="col-md-6">
            {% if metrics_available %}
                <h6 class="text-uppercase small text-muted mb-2">Report statistics</h6>
                <div class="d-flex flex-row flex-wrap gap-2 mb-2">
                    {{ metric_tile(measured_word_count, 'Words') }}
                    {{ metric_tile(page_count, 'Pages') }}
                    {{ metric_tile(figure_count, 'Figures') }}
                    {{ metric_tile(table_count, 'Tables') }}
                </div>
                {% if appendix_word_count is not none %}
                    <div class="small text-muted mb-1">Appendix: {{ appendix_word_count }} words</div>
                {% endif %}
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

            {# AI declaration (neutral informational styling) + compliance verdict attached directly beneath.
               Only shown when not restricted and a declaration was detected — both are driven by the same
               genai_statement_found flag, so they co-occur cleanly. ai_compliance_factor is None when the
               record is restricted or has no declaration (in which case the factor stays in the right column). #}
            {% if not restricted and genai_status is not none %}
                <h6 class="text-uppercase small text-muted mt-2 mb-2">AI declaration</h6>
                {% if genai_status %}
                    <div class="rounded mb-3" style="background: var(--bs-secondary-bg); border: 1px solid var(--bs-border-color)">
                        <div class="p-2 small">
                            <i class="fas fa-info-circle fa-fw me-1" style="color: var(--bs-secondary-color)"></i>
                            <strong class="text-body-secondary">Statement detected:</strong>
                            <span class="text-body">{{ genai_statement }}</span>
                        </div>
                        {% if ai_compliance_factor is not none %}
                            <hr class="my-0" style="border-color: var(--bs-border-color)">
                            <div class="p-2 small">
                                {% if ai_compliance_factor.resolved %}
                                    <div class="d-flex flex-row flex-wrap align-items-center gap-1 mb-1">
                                        <span class="badge bg-success-subtle text-success-emphasis border border-success-subtle">
                                            <i class="fas fa-check-circle fa-fw"></i> AI compliance statement
                                        </span>
                                        <span class="text-muted">
                                            {% if ai_compliance_factor.resolved_by_name %}resolved by {{ ai_compliance_factor.resolved_by_name }}{% else %}resolved{% endif %}
                                            {% if ai_compliance_factor.resolved_at_display %}&middot; {{ ai_compliance_factor.resolved_at_display }}{% endif %}
                                        </span>
                                    </div>
                                {% else %}
                                    <div class="mb-1">
                                        <span class="badge bg-warning-subtle text-warning-emphasis border border-warning-subtle">
                                            <i class="fas fa-exclamation-circle fa-fw"></i> AI compliance statement &mdash; pending review
                                        </span>
                                    </div>
                                {% endif %}
                                {% if ai_compliance_factor.annotation %}
                                    <div class="text-muted mt-1 ps-2" style="border-left: 2px solid var(--bs-border-color)">{{ ai_compliance_factor.annotation }}</div>
                                {% endif %}
                            </div>
                        {% endif %}
                    </div>
                {% else %}
                    <div class="small text-muted mb-3">No AI declaration found in report.</div>
                {% endif %}
            {% endif %}
        </div>

        <div class="col-md-6">
            {# Risk factors: AI compliance statement has been relocated to the left column (attached to the
               declaration). This column shows all remaining factors only. #}
            {% if other_rf_has_any %}
                <h6 class="text-uppercase small text-muted mb-2">Risk factors</h6>
                <div class="d-flex flex-column gap-2 mb-3">
                    {% for f in other_rf_factors %}
                        <div class="rounded" style="border: 1px solid var(--bs-border-color); overflow: hidden">
                            <div class="d-flex flex-row align-items-center gap-2 px-2 py-1"
                                 style="background: var(--bs-tertiary-bg); border-bottom: 1px solid var(--bs-border-color)">
                                {% if f.resolved %}
                                    <i class="fas fa-check-circle small" style="color: var(--bs-success-text-emphasis)"></i>
                                    <span class="small fw-semibold" style="color: var(--bs-success-text-emphasis)">{{ f.label }}</span>
                                {% else %}
                                    <i class="fas fa-exclamation-triangle small" style="color: var(--bs-danger-text-emphasis)"></i>
                                    <span class="small fw-semibold" style="color: var(--bs-danger-text-emphasis)">{{ f.label }}</span>
                                {% endif %}
                            </div>
                            <div class="px-2 py-1">
                                {% if f.resolved %}
                                    <div class="small text-muted">
                                        {% if f.resolved_by_name %}Resolved by {{ f.resolved_by_name }}{% else %}Resolved{% endif %}
                                        {% if f.resolved_at_display %}&middot; {{ f.resolved_at_display }}{% endif %}
                                    </div>
                                {% endif %}
                                {% if f.annotation %}
                                    <div class="small text-muted mt-1" style="border-left: 2px solid var(--bs-border-color); padding-left: 6px">{{ f.annotation }}</div>
                                {% endif %}
                            </div>
                        </div>
                    {% endfor %}
                </div>
            {% endif %}

            {% if feedback_links|length > 0 %}
                <h6 class="text-uppercase small text-muted mb-2">Feedback documents</h6>
                <div class="d-flex flex-row flex-wrap gap-2">
                    {% for fl in feedback_links %}
                        <a class="btn btn-xs btn-outline-secondary" href="{{ fl.url }}"
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


# language=jinja2
_grade = """
<div class="text-end">
    <div class="fw-semibold">
        {% if report_grade is not none %}{{ "%.1f"|format(report_grade) }}%{% else %}&mdash;{% endif %}
    </div>
    {% if grade_data|length > 0 %}
        <div class="mt-1 d-flex justify-content-end">
            <div class="sv2-metric-cap grades">
                <div class="sv2-metric-cap-label">Grades</div>
                <div class="sv2-metric-cap-body">
                    {% for g in grade_data %}
                        {% if not loop.first %}<div class="sv2-m-sep"></div>{% endif %}
                        <div class="sv2-m-item">
                            <div class="sv2-m-lbl">{{ g.label }}</div>
                            {% if g.grade is not none %}
                                <div class="sv2-m-val sv2-mv-ok">{{ "%.1f"|format(g.grade) }}%</div>
                            {% else %}
                                <div class="sv2-m-val sv2-mv-dim">&mdash;</div>
                            {% endif %}
                        </div>
                    {% endfor %}
                </div>
            </div>
        </div>
    {% endif %}
</div>
"""


def _build_grade_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_grade)


def _build_report_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_report)


def _build_details_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_details)


def _identity_line_parts(
    record: SubmissionRecord,
    simple_label,
) -> List:
    """Build the ordered list of fragments for the Report panel's identity line:
    programme, research group, project class (colour badge, kept inline per the
    agreed two-column design), year, submission period. All plain text except
    the project-class badge. Grades are shown in the right-column grade capsule."""
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


def _role_report_url_map(roles: List[SubmissionRole]) -> Dict[int, str]:
    """Map SubmissionRole.id → report URL for clickable role-holder names in the staff block.
    Roles without a report yet produce no entry (the name renders as plain text).

    The AVD dashboard's only possible viewers are root, admin, and data_dashboard_reports
    (_can_access_avd_dashboard() — no convenor/plain-faculty branch). admin/root keep using
    the live faculty.moderator_report_form route; a data_dashboard_reports viewer is routed
    to the read-only faculty.view_moderator_report instead."""
    url_map: Dict[int, str] = {}
    for role in roles:
        if role.role == SubmissionRole.ROLE_MODERATOR:
            report = role.moderator_reports.order_by(ModeratorReport.creation_timestamp.desc(), ModeratorReport.id.desc()).first()
            if report is not None:
                if current_user.has_role("admin") or current_user.has_role("root"):
                    url_map[role.id] = url_for(
                        "faculty.moderator_report_form",
                        mod_report_id=report.id,
                        url=url_for("dashboards.avd_dashboard"),
                    )
                else:
                    url_map[role.id] = url_for(
                        "faculty.view_moderator_report",
                        mod_report_id=report.id,
                        url=url_for("dashboards.avd_dashboard"),
                    )
        else:
            report = role.marking_reports.order_by(MarkingReport.creation_timestamp.desc(), MarkingReport.id.desc()).first()
            if report is not None:
                url_map[role.id] = url_for(
                    "faculty.view_marking_report",
                    report_id=report.id,
                    url=url_for("dashboards.avd_dashboard"),
                )
    return url_map


def _group_and_sort_roles(roles: List[SubmissionRole]) -> List[Tuple[int, List[SubmissionRole]]]:
    """Group roles by type and sort by the fixed priority order in _ROLE_PRIORITY.
    Role types not listed there (e.g. Exam board, External examiner) sort after all
    named types, preserving the generic iteration property from Phase 4."""
    groups: Dict[int, List[SubmissionRole]] = {}
    for role in roles:
        groups.setdefault(role.role, []).append(role)
    return sorted(groups.items(), key=lambda item: _ROLE_PRIORITY.get(item[0], _ROLE_PRIORITY_DEFAULT))


def _feedback_links(record: SubmissionRecord) -> List[Dict]:
    """Download links for this record's generated feedback report PDFs."""
    return [{"url": url_for("admin.download_generated_asset", asset_id=fr.asset_id)} for fr in record.feedback_reports.all() if fr.asset is not None]


def _details_context(record: SubmissionRecord) -> Dict:
    """Build the template context for the details child-row panel: language-analysis
    metrics, AI declaration, LLM report summary, full risk-factor breakdown, and
    feedback document links.

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

    The AI compliance statement risk factor is split from other risk factors and
    attached to the AI declaration section in the template when the record has a
    declaration and is not restricted. When restricted, or when no declaration exists,
    the compliance factor (if present) remains in the right-column risk factor list.
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

    # Split AI compliance factor from other risk factors. When a non-restricted record has a
    # declaration (genai_status True), the compliance factor is attached directly beneath the
    # declaration box in the left column. Otherwise it stays in the right-column risk factor list.
    ai_compliance_factor = None
    other_rf_factors = list(rf["factors"])
    if not restricted and genai_status:
        ai_compliance_factor = next((f for f in rf["factors"] if f["key"] == SubmissionRecord.RISK_AI_COMPLIANCE), None)
        if ai_compliance_factor is not None:
            other_rf_factors = [f for f in rf["factors"] if f["key"] != SubmissionRecord.RISK_AI_COMPLIANCE]
    other_rf_has_any = len(other_rf_factors) > 0

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
        "ai_compliance_factor": ai_compliance_factor,
        "other_rf_factors": other_rf_factors,
        "other_rf_has_any": other_rf_has_any,
        "feedback_links": feedback_links,
        "rf": rf,
        "has_details": bool(
            metrics_available or genai_status is not None or report_summary or rf["has_any_present"] or feedback_links or restricted
        ),
    }


def avd_dashboard_rows(records: List[SubmissionRecord]):
    """Row formatter for the AVD dashboard: one row per SubmissionRecord
    belonging to a closed SubmissionPeriodRecord. Two columns: a single rich
    "Report" panel (student, project, identity line, consent, flags, staff
    roles, downloads) and the sortable "Report grade" column."""
    simple_label = get_template_attribute("labels.html", "simple_label")

    report_templ: Template = _build_report_templ()
    grade_templ: Template = _build_grade_templ()
    details_templ: Template = _build_details_templ()

    data = []
    for record in records:
        report_grade = float(record.report_grade) if record.report_grade is not None else None
        grade_data = record.grade_display_data()

        roles = record.roles.all()
        has_moderator_role = any(r.role == SubmissionRole.ROLE_MODERATOR for r in roles)
        latest_sr = _latest_submitter_report(record)
        moderation_outcome = _moderation_outcome_text(latest_sr) if has_moderator_role else None
        convenor_intervention = bool(latest_sr is not None and latest_sr.convenor_intervention)
        out_of_tolerance_unassigned = bool(latest_sr is not None and latest_sr.out_of_tolerance and not has_moderator_role)

        identity_parts = _identity_line_parts(record, simple_label)

        grouped_roles = _group_and_sort_roles(roles)
        role_report_urls = _role_report_url_map(roles)

        details_ctx = _details_context(record)
        ai_risk = _ai_risk_summary(details_ctx["rf"])

        data.append(
            {
                "report": {
                    "display": render_template(
                        report_templ,
                        record=record,
                        identity_parts=identity_parts,
                        grouped_roles=grouped_roles,
                        role_report_urls=role_report_urls,
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
                    "display": render_template(
                        grade_templ,
                        report_grade=report_grade,
                        grade_data=grade_data,
                    ),
                    "sortvalue": report_grade,
                },
                "details": render_template(details_templ, **details_ctx) if details_ctx["has_details"] else None,
            }
        )

    return data
