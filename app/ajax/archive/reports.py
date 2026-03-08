#
# Created by David Seery on 08/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List

from flask import render_template_string, get_template_attribute, current_app, render_template
from jinja2 import Template, Environment

from ...models import SubmittingStudent

# language=jinja2
_name = """
{% set student = sub.student %}
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
{% set config = sub.config %}
<div>
    <span class="badge bg-secondary">{{ config.year }}&ndash;{{ config.year + 1 }}</span>
</div>
<div class="mt-1">
    {{ simple_label(config.project_class.make_label()) }}
</div>
"""

# language=jinja2
_records = """
{% macro turnitin_info(r) %}
    {% if r.turnitin_outcome is not none or r.turnitin_score is not none %}
        <div class="mt-1 d-flex flex-row flex-wrap justify-content-start align-items-center gap-2">
            <span class="small text-muted fw-semibold">Turnitin</span>
            {% if r.turnitin_outcome is not none %}
                <span class="badge bg-secondary small">{{ r.turnitin_outcome }}</span>
            {% endif %}
            {% if r.turnitin_score is not none %}
                <span class="small">
                    Similarity: 
                    <strong class="{% if r.turnitin_score >= 30 %}text-danger{% elif r.turnitin_score >= 15 %}text-warning{% else %}text-success{% endif %}">
                        {{ r.turnitin_score }}%
                    </strong>
                </span>
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
{% macro role_list(roles, label) %}
    {% if roles|length > 0 %}
        <div class="d-flex flex-row flex-wrap justify-content-start align-items-baseline gap-1">
            <span class="small text-muted fw-semibold">{{ label }}:</span>
            {% for role in roles %}
                <span class="small">
                    <a class="text-decoration-none" href="mailto:{{ role.user.email }}">{{ role.user.name }}</a>
                    {% if role.grade is not none %}
                        <span class="ms-1 {% if role.signed_off %}text-primary{% else %}text-secondary{% endif %}">
                            {{ role.grade }}%
                        </span>
                    {% endif %}
                </span>
            {% endfor %}
        </div>
    {% endif %}
{% endmacro %}
{% set recs = sub.ordered_assignments.all() %}
{% if recs|length == 0 %}
    <span class="badge bg-secondary">No submissions</span>
{% else %}
    {% for r in recs %}
        <div class="bg-light p-2 mb-2 rounded">
            {% set period = r.period %}
            <div class="d-flex flex-row justify-content-between align-items-start gap-2">
                <div class="flex-grow-1">
                    {% if r.project is not none %}
                        <div class="fw-semibold small">{{ r.project.name }}</div>
                    {% else %}
                        <div class="small text-muted fst-italic">No project assigned</div>
                    {% endif %}
                    {% if period is not none %}
                        <div class="small text-muted">{{ period.display_name }}</div>
                    {% endif %}

                    {# Grades #}
                    {% if r.supervision_grade is not none or r.report_grade is not none %}
                        <div class="d-flex flex-row flex-wrap justify-content-start align-items-center gap-3 mt-1">
                            {% if r.supervision_grade is not none %}
                                <div>
                                    <div class="small text-muted">Supervision</div>
                                    <div class="fw-bold text-success">{{ r.supervision_grade|round(1) }}%</div>
                                </div>
                            {% endif %}
                            {% if r.report_grade is not none %}
                                <div>
                                    <div class="small text-muted">Report</div>
                                    <div class="fw-bold text-success">{{ r.report_grade|round(1) }}%</div>
                                </div>
                            {% endif %}
                        </div>
                    {% endif %}

                    {# Roles #}
                    {% set supervisor_roles = r.supervisor_roles %}
                    {% set marker_roles = r.marker_roles %}
                    {% set moderator_roles = r.moderator_roles %}
                    <div class="mt-1 d-flex flex-column justify-content-start align-items-start gap-1">
                        {{ role_list(supervisor_roles, 'Supervisors') }}
                        {{ role_list(marker_roles, 'Markers') }}
                        {{ role_list(moderator_roles, 'Moderators') }}
                    </div>

                    {# Turnitin data #}
                    {{ turnitin_info(r) }}
                </div>

                {# Download buttons #}
                <div class="d-flex flex-column justify-content-start align-items-end gap-1">
                    {% if r.report_secret %}
                        <span class="text-danger"><i class="fas fa-exclamation-circle"></i> Report restricted</span>
                    {% elif r.report_embargo %}
                        <span class="text-danger"><i class="fas fa-exclamation-circle"></i> Embargoed until {{ r.report.embargo.strftime("%a %d %b %Y %H:%M") }}</span>
                    {% else %}
                        {% if r.report is not none %}
                            <a class="btn btn-xs btn-outline-primary"
                               href="{{ url_for('admin.download_submitted_asset', asset_id=r.report_id) }}"
                               data-bs-toggle="tooltip" title="Download original report">
                                <i class="fas fa-file-download fa-fw"></i> Original
                            </a>
                        {% endif %}
                        {% if r.processed_report is not none %}
                            <a class="btn btn-xs btn-outline-secondary"
                               href="{{ url_for('admin.download_generated_asset', asset_id=r.processed_report_id) }}"
                               data-bs-toggle="tooltip" title="Download processed report">
                                <i class="fas fa-file-pdf fa-fw"></i> Processed
                            </a>
                        {% endif %}
                        {% if r.report is none and r.processed_report is none %}
                            <span class="badge bg-light text-muted border">No report</span>
                        {% endif %}
                    {% endif %}
                </div>
            </div>
        </div>
    {% endfor %}
{% endif %}
"""

def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)

def _build_year_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_year)

def _build_records_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_records)


def retired_reports(students: List[SubmittingStudent]):
    simple_label = get_template_attribute("labels.html", "simple_label")

    name_templ: Template = _build_name_templ()
    year_templ: Template = _build_year_templ()
    records_templ: Template = _build_records_templ()

    data = [
        {
            "name": {
                "display": render_template(name_templ, sub=s, simple_label=simple_label),
                "sortstring": s.student.user.last_name + s.student.user.first_name,
            },
            "year": {
                "display": render_template(year_templ, sub=s, simple_label=simple_label),
                "sortvalue": s.config.year,
            },
            "records": render_template(records_templ, sub=s),
        }
        for s in students
    ]

    return data
