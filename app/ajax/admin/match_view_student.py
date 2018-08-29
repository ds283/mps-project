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
{{ sel.student.programme.label|safe }}
{{ sel.academic_year_label|safe }}
{{ sel.student.cohort_label|safe }}
"""


_project = \
"""
{% macro project_tag(r, show_period) %}
    {% set adjustable = false %}
    {% if r.selector.has_submitted or r.selector.has_bookmarks %}{% set adjustable = true %}{% endif %}
    <div class="{% if adjustable %}dropdown{% else %}disabled{% endif %} match-assign-button" style="display: inline-block;">
        <a class="label {% if r.is_project_overassigned %}label-danger{% else %}label-info{% endif %} {% if adjustable %}dropdown-toggle{% endif %}" {% if adjustable %}type="button" data-toggle="dropdown"{% endif %}>
            {% if show_period %}#{{ r.submission_period }}: {% endif %}{{ r.supervisor.user.name }} (No. {{ r.project.number }})
            <span class="caret"></span>
        </a>
        {% if adjustable %}
            {% if r.selector.has_submitted %}{% set list = r.selector.ordered_selection %}
            {% elif r.rselector.has_bookmarks %}{% set list = r.selector.ordered_bookmarks %}
            {% endif %}
            <ul class="dropdown-menu">
                {% if r.selector.has_submitted %}
                    <li class="dropdown-header">Submitted choices</li>
                {% elif r.selector.has_bookmarks %}
                    <li class="dropdown-header">Ranked bookmarks</li>
                {% endif %}
                {% for item in list %}
                    {% set disabled = false %}
                    {% if item.liveproject_id == r.project_id %}{% set disabled = true %}{% endif %}
                    <li {% if disabled %}class="disabled"{% endif %}>
                        <a {% if not disabled %}href="{{ url_for('admin.reassign_match_project', id=r.id, pid=item.liveproject_id) }}"{% endif %}>
                           #{{ item.rank }}:
                           {{ item.liveproject.owner.user.name }} - No. {{ item.liveproject.number }}: {{ item.liveproject.name }} 
                        </a>
                    </li> 
                {% endfor %}
            </ul>
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
        <div class="has-error">
            <p class="help-block">{% if recs|length > 1 %}#{{ r.submission_period }}: {% endif %}{{ r.error }}</p>
        <div class="has-error">
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
                {% for marker in r.project.second_markers %}
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


def student_view_data(selector_data):

    # selector_data is a list of ((lists of) MatchingRecord, delta-value) pairs

    data = [{'student': {
                'display': render_template_string(_student, sel=r[0].selector, valid=all([rc.is_valid and not rc.is_project_overassigned for rc in r])),
                'sortvalue': r[0].selector.student.user.last_name + r[0].selector.student.user.first_name
             },
             'pclass': render_template_string(_pclass, sel=r[0].selector),
             'cohort': render_template_string(_cohort, sel=r[0].selector),
             'project': render_template_string(_project, recs=r),
             'marker': render_template_string(_marker, recs=r),
             'rank': {
                'display': render_template_string(_rank, recs=r, delta=d),
                'sortvalue': d
             } } for r, d in selector_data]

    return jsonify(data)
