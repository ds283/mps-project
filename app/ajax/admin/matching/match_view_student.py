#
# Created by David Seery on 22/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, render_template_string


# language=jinja2
_student = \
"""
<a class="text-decoration-none" href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
{% if not valid %}
    <i class="fas fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
{% if not sel.convert_to_submitter %}
    <div class="error-block">
        <div class="error-message">
            Conversion of this student is disabled.
        </div>
    <div>
    <div>
        <a class="btn btn-sm btn-danger" href="{{ url_for('admin.delete_match_record', record_id=record_id) }}">
            Delete
        </a>
    </div>
{% endif %}
"""


# language=jinja2
_pclass = \
"""
{% set config = sel.config %}
{% set pclass = config.project_class %}
{% set style = pclass.make_CSS_style() %}
<a class="badge text-decoration-none text-nohover-light {% if style %}bg-secondary{% else %}bg-info{% endif %} btn-table-block"
   {% if style %}style="{{ style }}"{% endif %}
   href="mailto:{{ config.convenor_email }}">
    {{ pclass.abbreviation }} ({{ config.convenor_name }})
</a>
"""


# language=jinja2
_cohort = \
"""
{{ sel.student.programme.short_label|safe }}
{{ sel.academic_year_label(show_details=True)|safe }}
{{ sel.student.cohort_label|safe }}
"""


# language=jinja2
_project = \
"""
{% macro truncate_name(name, maxlength=25) %}
    {%- if name|length > maxlength -%}
        {{ name[0:maxlength] }}...
    {%- else -%}
        {{ name }}
    {%- endif -%}
{% endmacro %}
{% macro project_tag(r, show_period) %}
    {% set adjustable = false %}
    {% if r.selector.has_submission_list %}{% set adjustable = true %}{% endif %}
    {% set pclass = r.selector.config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    {% set has_issues = r.has_issues %}
    {% set supervisors = r.supervisor_roles %}
    <div>
        <div class="{% if adjustable %}dropdown{% else %}disabled{% endif %} match-assign-button" style="display: inline-block;">
            <a class="badge text-decoration-none text-nohover-light {% if has_issues %}bg-danger{% elif style %}bg-secondary{% else %}bg-info{% endif %} {% if adjustable %}dropdown-toggle{% endif %}"
                    {% if not has_issues and style %}style="{{ style }}"{% endif %}
                    {% if adjustable %}data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false"{% endif %}>
                {% if show_period %}#{{ r.submission_period }}: {% endif %}
                {% if supervisors|length > 0 %}
                    {{ truncate_name(r.project.name) }} ({{ supervisors[0].last_name }}{%- if r.project.generic -%}, generic{%- endif -%})
                {% endif %}
            </a>
            {% if adjustable %}
                {% set list = r.selector.ordered_selections %}
                <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                    <div class="dropdown-header">Submitted choices</div>
                    {% for item in list %}
                        {% set disabled = false %}
                        {% set project = item.liveproject %}
                        {% if item.liveproject_id == r.project_id or not item.is_selectable %}{% set disabled = true %}{% endif %}
                        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.reassign_match_project', id=r.id, pid=item.liveproject_id) }}"{% endif %}>
                           #{{ item.rank }}: {{ item.format_project()|safe }}
                           {% if project.generic or project.owner is none %}
                              (generic)
                           {% else %}
                              ({{ project.owner.user.name }})
                           {% endif %}
                           {% if r.original_project_id == item.liveproject_id %}
                              [automatch]
                           {% endif %}
                        </a>
                    {% endfor %}
                    <div role="separator" class="dropdown-divider"></div>
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.reassign_supervisor_roles', rec_id=r.id, url=url_for('admin.match_student_view', id=r.matching_id)) }}">
                        Edit supervisor roles...
                    </a>                
                </div>
            {% endif %}
        </div>
        {% set outcome = r.hint_status %}
        {% if outcome is not none %}
            {% set satisfied, violated = outcome %}
            {% if satisfied|length > 0 %}
                <span class="badge bg-success">{%- for i in range(satisfied|length) -%}<i class="fas fa-check"></i>{%- endfor %} HINT</span>
            {% endif %}
            {% if violated|length > 0 %}
                <span class="badge bg-warning text-dark">{%- for i in range(violated|length) -%}<i class="fas fa-times"></i>{%- endfor %} HINT</span>
            {% endif %}
        {% endif %}
        {% set prog_status = r.project.satisfies_preferences(r.selector) %}
        {% if prog_status is not none %}
            {% if prog_status %}
                <span class="badge bg-success"><i class="fas fa-check"></i> PROG</span>
            {% else %}
                <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> PROG</span>
            {% endif %}
        {% endif %}
    </div>
{% endmacro %}
{% if recs|length == 1 %}
    {{ project_tag(recs[0], false) }}
{% elif recs|length > 1 %}
    {% for r in recs %}
        {{ project_tag(r, true) }}
    {% endfor %}
{% endif %}
{% for r in recs %}
    {# if both not valid and overassigned, should leave error message from is_valid intact due to short-circuit evaluation #}
    {% if not r.is_valid or r.has_issues %}
        <p></p>
        {% set errors = r.errors %}
        {% set warnings = r.warnings %}
        {% if errors|length == 1 %}
            <span class="badge bg-danger">1 error</span>
        {% elif errors|length > 1 %}
            <span class="badge bg-danger">{{ errors|length }} errors</span>
        {% endif %}
        {% if warnings|length == 1 %}
            <span class="badge bg-warning text-dark">1 warning</span>
        {% elif warnings|length > 1 %}
            <span class="badge bg-warning text-dark">{{ warnings|length }} warnings</span>
        {% endif %}
        {% if errors|length > 0 %}
            <div class="error-block">
                {% for item in errors %}
                    {% if loop.index <= 10 %}
                        <div class="error-message">{{ item }}</div>
                    {% elif loop.index == 11 %}
                        <div class="error-message">...</div>
                    {% endif %}            
                {% endfor %}
            </div>
        {% endif %}
        {% if warnings|length > 0 %}
            <div class="error-block">
                {% for item in warnings %}
                    {% if loop.index <= 10 %}
                        <div class="error-message">Warning: {{ item }}</div>
                    {% elif loop.index == 11 %}
                        <div class="error-message">Further errors suppressed...</div>
                    {% endif %}
                {% endfor %}
            </div>
        {% endif %}
    {% endif %}
{% endfor %}
"""


# language=jinja2
_marker = \
"""
{% macro marker_tag(r, show_period) %}
    {% set markers = r.marker_roles %}
    {% for marker in markers %}
        <div class="dropdown match-assign-button" style="display: inline-block;">
            <a class="badge text-decoration-none text-nohover-dark bg-light dropdown-toggle" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                {% if show_period %}#{{ r.submission_period }}: {% endif %}{{ marker.name }}
            </a>
            <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                <div class="dropdown-header">Reassign marker</div>
                {% set assessor_list = r.project.assessor_list %}
                {% for fac in assessor_list %}
                    {% set disabled = false %}
                    {% if fac.id == marker.id %}{% set disabled = true %}{% endif %}
                    <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.reassign_match_marker', id=r.id, mid=fac.id) }}"{% endif %}>
                        {{ fac.user.name }}
                    </a>
                {% endfor %}
            </div>
        </div>
    {% else %}
        <span class="badge bg-light text-dark">None</span>
    {% endfor %}
{% endmacro %}
{% if recs|length == 1 %}
    {{ marker_tag(recs[0], false) }}
{% elif recs|length > 1 %}
    {% for r in recs %}
        {{ marker_tag(r, true) }}
    {% endfor %}
{% endif %}
"""


# language=jinja2
_rank = \
"""
{% if recs|length == 1 %}
    {% set r = recs[0] %}
    <span class="badge {% if r.hi_ranked %}bg-success{% elif r.lo_ranked %}bg-warning text-dark{% else %}bg-info{% endif %}">{{ r.rank }}</span>
    <span class="badge bg-primary">&delta; = {{ delta }}</span>
{% elif recs|length > 1 %}
    {% for r in recs %}
        <span class="badge {% if r.hi_ranked %}bg-success{% elif r.lo_ranked %}bg-warning text-dark{% else %}bg-info{% endif %}">#{{ r.submission_period }}: {{ r.rank }}</span>
    {% endfor %}
    <span class="badge bg-primary">&delta; = {{ delta }}</span>
{% endif %}
"""


# language=jinja2
_scores = \
"""
{% if recs|length == 1 %}
    {% set r = recs[0] %}
    <span class="badge bg-primary">{{ r.current_score|round(precision=2) }}</span>
{% elif recs|length > 1 %}
    {% for r in recs %}
        <span class="badge bg-secondary">#{{ r.submission_period }}: {{ r.current_score|round(precision=2) }}</span>
    {% endfor %}
    <span class="badge bg-primary">Total {{ total_score|round(precision=2) }}</span>
{% endif %}
"""


def student_view_data(selector_data):
    # selector_data is a list of ((lists of) MatchingRecord, delta-value) pairs

    def score_data(r):
        total = sum([rec.current_score for rec in r])

        return {'display': render_template_string(_scores, recs=r, total_score=total),
                'sortvalue': total}

    data = [{'student': {
                'display': render_template_string(_student, sel=r[0].selector, record_id=r[0].id,
                                                  valid=all([not rc.has_issues for rc in r])),
                'sortvalue': r[0].selector.student.user.last_name + r[0].selector.student.user.first_name
             },
             'pclass': render_template_string(_pclass, sel=r[0].selector),
             'details': render_template_string(_cohort, sel=r[0].selector),
             'project': render_template_string(_project, recs=r),
             'marker': render_template_string(_marker, recs=r),
             'rank': {
                'display': render_template_string(_rank, recs=r, delta=d),
                'sortvalue': d
             },
             'scores': score_data(r)} for r, d in selector_data]

    return jsonify(data)
