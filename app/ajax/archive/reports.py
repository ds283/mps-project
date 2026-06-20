#
# Created by David Seery on 08/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List, Optional, Tuple

from flask import (
    get_template_attribute,
    current_app,
    render_template,
)
from jinja2 import Template, Environment

from ...models import SubmissionRecord

# language=jinja2
_name = """
{% set student = record.owner.student %}
{% set user = student.user %}
{% set programme = student.programme %}
<div>
    <a class="text-decoration-none" href="mailto:{{ user.email }}">{{ user.name }}</a>
</div>
{% if programme is not none %}
    <div class="mt-1">
        {{ simple_label(programme.label) }}
    </div>
{% endif %}
"""

# language=jinja2
_year = """
{% set config = record.period.config %}
<div>
    <span class="badge bg-secondary">{{ config.year }}&ndash;{{ config.year + 1 }}</span>
</div>
<div class="mt-1">
    {{ simple_label(config.project_class.make_label()) }}
</div>
"""

# language=jinja2
_report = """
{% macro turnitin_info(r) %}
    {# turnitin_outcome is a legacy Canvas LMS field not used in current Turnitin outputs; hidden from display #}
    {% if r.turnitin_score is not none %}
        <div class="mt-1 d-flex flex-row flex-wrap justify-content-start align-items-center gap-2">
            <span class="small text-muted fw-semibold">Turnitin</span>
            {% if r.turnitin_score is not none %}
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
            {% endif %}
            {% if r.turnitin_web_overlap is not none %}
                <span class="small text-muted">Web: {{ r.turnitin_web_overlap }}%</span>
            {% endif %}
            {% if r.turnitin_publication_overlap is not none %}
                <span class="small text-muted">Pub: {{ r.turnitin_publication_overlap }}%</span>
            {% endif %}
            {% if r.turnitin_student_overlap is not none %}
                <span class="small text-muted">Student: {{ r.turnitin_student_overlap }}%</span>
            {% endif %}
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
{% macro role_list(roles, label) %}
    {% if roles|length > 0 %}
        <div class="d-flex flex-row flex-wrap justify-content-start align-items-baseline gap-1">
            <span class="small text-muted fw-semibold">{{ label }}:</span>
            {% for role in roles %}
                <span class="small">
                    <a class="text-decoration-none" href="mailto:{{ role.user.email }}">{{ role.user.name }}</a>
                </span>
            {% endfor %}
        </div>
    {% endif %}
{% endmacro %}
{% set period = record.period %}
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
                <div class="d-flex flex-row flex-swap justify-content-start align-items-baseline gap-2">
                    {% if record.project is not none %}
                        <div class="fw-semibold small">{{ record.project.name }}</div>
                        {% if record.project.group is not none %}
                            <div class="mt-1">
                                {{ simple_label(record.project.group.make_label()) }}
                            </div>
                        {% endif %}
                    {% else %}
                        <div class="small text-muted fst-italic">No project assigned</div>
                    {% endif %}
                    {% if period is not none %}
                        <div class="small text-muted">{{ period.display_name }}</div>
                    {% endif %}
                </div>

                {# Consent badges #}
                {{ consent_badges(record) }}

                {# Supervision / presentation grades #}
                {% if supervision_grade is not none or presentation_grade is not none %}
                    <div class="small text-muted mt-1">
                        Supervision
                        {% if supervision_grade is not none %}{{ "%.1f"|format(supervision_grade) }}%{% else %}&mdash;{% endif %}
                        &middot;
                        Presentation
                        {% if presentation_grade is not none %}{{ "%.1f"|format(presentation_grade) }}%{% else %}&mdash;{% endif %}
                    </div>
                {% endif %}

                {# Roles #}
                {% set supervisor_roles = record.supervisor_roles %}
                {% set marker_roles = record.marker_roles %}
                {% set moderator_roles = record.moderator_roles %}
                <div class="mt-1 d-flex flex-column justify-content-start align-items-start gap-1">
                    {{ role_list(supervisor_roles, 'Supervisors') }}
                    {{ role_list(marker_roles, 'Markers') }}
                    {{ role_list(moderator_roles, 'Moderators') }}
                </div>

                {# Turnitin data #}
                {{ turnitin_info(record) }}
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


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_year_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_year)


def _build_report_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_report)


def _supervision_presentation_grades(
    record: SubmissionRecord,
) -> Tuple[Optional[float], Optional[float]]:
    """Return (supervision_grade, presentation_grade), or None for either when
    not yet graded or not applicable to this period's configuration."""
    grades = {g["label"]: g["grade"] for g in record.grade_display_data()}
    return grades.get("Supervision"), grades.get("Presentation")


def avd_dashboard_rows(records: List[SubmissionRecord]):
    """Row formatter for the AVD dashboard: one row per SubmissionRecord
    belonging to a closed SubmissionPeriodRecord."""
    simple_label = get_template_attribute("labels.html", "simple_label")

    name_templ: Template = _build_name_templ()
    year_templ: Template = _build_year_templ()
    report_templ: Template = _build_report_templ()

    data = []
    for record in records:
        supervision_grade, presentation_grade = _supervision_presentation_grades(record)

        report_grade = float(record.report_grade) if record.report_grade is not None else None

        data.append(
            {
                "name": {
                    "display": render_template(name_templ, record=record, simple_label=simple_label),
                    "sortstring": record.owner.student.user.last_name + record.owner.student.user.first_name,
                },
                "year": {
                    "display": render_template(year_templ, record=record, simple_label=simple_label),
                    "sortvalue": record.period.config.year,
                },
                "report_grade": {
                    "display": "{:.1f}%".format(report_grade) if report_grade is not None else "&mdash;",
                    "sortvalue": report_grade,
                },
                "records": render_template(
                    report_templ,
                    record=record,
                    simple_label=simple_label,
                    supervision_grade=supervision_grade,
                    presentation_grade=presentation_grade,
                ),
            }
        )

    return data
