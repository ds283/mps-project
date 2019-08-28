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


_student = \
"""
<a href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
{% if not valid %}
    <i class="fa fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
{% if not sel.convert_to_submitter %}
    <div class="has-error">
        <p class="help-block">
            Conversion of this student is disabled
            <a class="btn btn-sm btn-danger" href="{{ url_for('admin.delete_match_record', record_id=record_id) }}">
                Delete
            </a>
        </p>
    </div>
{% endif %}
"""


_pclass = \
"""
{% set pclass = sel.config.project_class %}
{% set style = pclass.make_CSS_style() %}
<a class="label {% if style %}label-default{% else %}label-info{% endif %} btn-table-block"
   {% if style %}style="{{ style }}"{% endif %}
   href="mailto:{{ pclass.convenor_email }}">
    {{ pclass.abbreviation }} ({{ pclass.convenor_name }})
</a>
"""


_cohort = \
"""
{{ sel.student.programme.short_label|safe }}
{{ sel.academic_year_label(show_details=True)|safe }}
{{ sel.student.cohort_label|safe }}
"""


_project = \
"""
{% macro project_tag(r, show_period) %}
    {% set adjustable = false %}
    {% if r.selector.has_submission_list %}{% set adjustable = true %}{% endif %}
    {% set pclass = r.selector.config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    {% set proj_overassigned = r.is_project_overassigned %}
    <div>
        <div class="{% if adjustable %}dropdown{% else %}disabled{% endif %} match-assign-button" style="display: inline-block;">
            <a class="label {% if proj_overassigned %}label-danger{% elif style %}label-default{% else %}label-info{% endif %} {% if adjustable %}dropdown-toggle{% endif %}"
                    {% if not proj_overassigned and style %}style="{{ style }}"{% endif %}
                    {% if adjustable %}type="button" data-toggle="dropdown"{% endif %}>{% if show_period %}#{{ r.submission_period }}: {% endif %}{{ r.supervisor.user.name }}
                (No. {{ r.project.number }})
                {% if adjustable %}<span class="caret"></span>{% endif %}</a>
            {% if adjustable %}
                {% set list = r.selector.ordered_selections %}
                <ul class="dropdown-menu">
                    <li class="dropdown-header">Submitted choices</li>
                    {% for item in list %}
                        {% set disabled = false %}
                        {% if item.liveproject_id == r.project_id or not item.is_selectable %}{% set disabled = true %}{% endif %}
                        <li {% if disabled %}class="disabled"{% endif %}>
                            <a {% if not disabled %}href="{{ url_for('admin.reassign_match_project', id=r.id, pid=item.liveproject_id) }}"{% endif %}>
                               #{{ item.rank }}:
                               {{ item.liveproject.owner.user.name }} &ndash; No. {{ item.liveproject.number }}: {{ item.format_project|safe }} 
                            </a>
                        </li> 
                    {% endfor %}
                </ul>
            {% endif %}
        </div>
        {% set outcome = r.hint_status %}
        {% if outcome is not none %}
            {% set satisfied, violated = outcome %}
            {% if satisfied|length > 0 %}
                <span class="label label-success">{%- for i in range(satisfied|length) -%}<i class="fa fa-check"></i>{%- endfor %} HINT</span>
            {% endif %}
            {% if violated|length > 0 %}
                <span class="label label-warning">{%- for i in range(violated|length) -%}<i class="fa fa-times"></i>{%- endfor %} HINT</span>
            {% endif %}
        {% endif %}
        {% set prog_status = r.project.satisfies_preferences(r.selector) %}
        {% if prog_status is not none %}
            {% if prog_status %}
                <span class="label label-success"><i class="fa fa-check"></i> PROG</span>
            {% else %}
                <span class="label label-warning"><i class="fa fa-times"></i> PROG</span>
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
    {% if not r.is_valid or r.is_project_overassigned %}
        <p></p>
        {% set errors = r.errors %}
        {% set warnings = r.warnings %}
        {% if errors|length == 1 %}
            <span class="label label-danger">1 error</span>
        {% elif errors|length > 1 %}
            <span class="label label-danger">{{ errors|length }} errors</span>
        {% else %}
            <span class="label label-success">0 errors</span>
        {% endif %}
        {% if warnings|length == 1 %}
            <span class="label label-warning">1 warning</span>
        {% elif warnings|length > 1 %}
            <span class="label label-warning">{{ warnings|length }} warnings</span>
        {% else %}
            <span class="label label-success">0 warnings</span>
        {% endif %}
        {% if errors|length > 0 %}
            <div class="has-error">
                {% for item in errors %}
                    {% if loop.index <= 10 %}
                        <p class="help-block">{{ item }}</p>
                    {% elif loop.index == 11 %}
                        <p class="help-block">...</p>
                    {% endif %}            
                {% endfor %}
            </div>
        {% endif %}
        {% if warnings|length > 0 %}
            <div class="has-error">
                {% for item in warnings %}
                    {% if loop.index <= 10 %}
                        <p class="help-block">Warning: {{ item }}</p>
                    {% elif loop.index == 11 %}
                        <p class="help-block">...</p>
                    {% endif %}
                {% endfor %}
            </div>
        {% endif %}
    {% endif %}
{% endfor %}
"""


_marker = \
"""
{% macro marker_tag(r, show_period) %}
    {% if r.marker %}
        <div class="dropdown match-assign-button" style="display: inline-block;">
            <a class="label label-default dropdown-toggle" type="button" data-toggle="dropdown">
                {% if show_period %}#{{ r.submission_period }}: {% endif %}{{ r.marker.user.name }}
                <span class="caret"></span>
            </a>
            <ul class="dropdown-menu">
                <li class="dropdown-header">Reassign 2nd marker</li>
                {% set assessor_list = r.project.assessor_list %}
                {% for marker in assessor_list %}
                    {% set disabled = false %}
                    {% if marker.id == r.marker_id %}{% set disabled = true %}{% endif %}
                    <li {% if disabled %}class="disabled"{% endif %}>
                        <a {% if not disabled %}href="{{ url_for('admin.reassign_match_marker', id=r.id, mid=marker.id) }}"{% endif %}>
                            {{ marker.user.name }}
                        </a>
                    </li>
                {% endfor %}
            </ul>
        </div>
    {% else %}
        <span class="label label-default">None</span>
    {% endif %}
{% endmacro %}
{% if recs|length == 1 %}
    {{ marker_tag(recs[0], false) }}
{% elif recs|length > 1 %}
    {% for r in recs %}
        {{ marker_tag(r, true) }}
    {% endfor %}
{% endif %}
"""


_rank = \
"""
{% if recs|length == 1 %}
    {% set r = recs[0] %}
    <span class="label {% if r.hi_ranked %}label-success{% elif r.lo_ranked %}label-warning{% else %}label-info{% endif %}">{{ r.rank }}</span>
    <span class="label label-primary">&delta; = {{ delta }}</span>
{% elif recs|length > 1 %}
    {% for r in recs %}
        <span class="label {% if r.hi_ranked %}label-success{% elif r.lo_ranked %}label-warning{% else %}label-info{% endif %}">#{{ r.submission_period }}: {{ r.rank }}</span>
    {% endfor %}
    <span class="label label-primary">&delta; = {{ delta }}</span>
{% endif %}
"""


_scores = \
"""
{% if recs|length == 1 %}
    {% set r = recs[0] %}
    <span class="label label-primary">{{ r.current_score|round(precision=2) }}</span>
{% elif recs|length > 1 %}
    {% for r in recs %}
        <span class="label label-default">#{{ r.submission_period }}: {{ r.current_score|round(precision=2) }}</span>
    {% endfor %}
    <span class="label label-primary">Total {{ total_score|round(precision=2) }}</span>
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
                                                  valid=all([rc.is_valid and
                                                             not rc.is_project_overassigned for rc in r])),
                'sortvalue': r[0].selector.student.user.last_name + r[0].selector.student.user.first_name
             },
             'pclass': render_template_string(_pclass, sel=r[0].selector),
             'cohort': render_template_string(_cohort, sel=r[0].selector),
             'project': render_template_string(_project, recs=r),
             'marker': render_template_string(_marker, recs=r),
             'rank': {
                'display': render_template_string(_rank, recs=r, delta=d),
                'sortvalue': d
             },
             'scores': score_data(r)} for r, d in selector_data]

    return jsonify(data)
