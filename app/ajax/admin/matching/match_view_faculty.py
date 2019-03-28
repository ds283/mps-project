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

from ....database import db
from ....models import MatchingRecord

_name = \
"""
<a href="mailto:{{ f.user.email }}">{{ f.user.name }}</a>
{% if overassigned %}
    <i class="fa fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
"""


_projects = \
"""
{% macro project_tag(r) %}
    {% set adjustable = false %}
    {% if r.selector.has_submitted %}{% set adjustable = true %}{% endif %}
    {% set pclass = r.selector.config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    <div class="{% if adjustable %}dropdown{% else %}disabled{% endif %} match-assign-button" style="display: inline-block;">
        <a class="label {% if r.is_project_overassigned %}label-danger{% elif style %}label-default{% else %}label-info{% endif %} btn-table-block {% if adjustable %}dropdown-toggle{% endif %}"
                {% if not r.is_project_overassigned and style %}style="{{ style }}"{% endif %}
                {% if adjustable %}type="button" data-toggle="dropdown"{% endif %}>#{{ r.submission_period }}:
            {{ r.selector.student.user.name }} (No. {{ r.project.number }})
        {% if adjustable %}<span class="caret"></span>{% endif %}</a>
        {% if adjustable %}
            {% set list = r.selector.ordered_selection %}
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
                           {{ item.liveproject.owner.user.name }} &ndash; No. {{ item.liveproject.number }}: {{ item.format_project|safe }} 
                        </a>
                    </li> 
                {% endfor %}
            </ul>
        {% endif %}
        {% set outcome = r.hint_status %}
        {% if outcome is not none %}
            {% set satisfied, violated = outcome %}
            {% if satisfied|length > 0 %}
                <span class="label label-success">{% for i in range(satisfied|length) %}<i class="fa fa-check"></i>{% endfor %}</span>
            {% endif %}
            {% if violated|length > 0 %}
                <span class="label label-warning">{% for i in range(violated|length) %}<i class="fa fa-times"></i>{% endfor %}</span>
            {% endif %}
        {% endif %}
    </div>
{% endmacro %}
{% set ns = namespace(count=0) %}
{% for r in recs %}
    {% if pclass_filter is none or r.selector.config.pclass_id == pclass_filter %}
        {% set ns.count = ns.count + 1 %}
        {{ project_tag(r) }}
    {% endif %}
{% endfor %}
{% if ns.count == 0 %}
    <span class="label label-default btn-table-block">None</span>
{% endif %}
{% if overassigned %}
    <div class="has-error">
        <p class="help-block">Supervising workload exceeds CATS limit (assigned={{ assigned }}, max capacity={{ lim }})</p>
    </div>
{% endif %}
{% if err_msgs|length > 0 %}
    <div class="has-error">
        {% for msg in err_msgs %}
            <p class="help-block">{{ msg }}</p>
        {% endfor %}
    </div>
{% endif %}
"""


_marking = \
"""
{% macro marker_tag(r) %}
    {% set pclass = r.selector.config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    <div class="dropdown match-assign-button" style="display: inline-block;">
        <a class="label {% if style %}label-default{% else %}label-info{% endif %} btn-table-block dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} type="button" data-toggle="dropdown">
            #{{ r.submission_period }}: {{ r.selector.student.user.name }} (No. {{ r.project.number }})
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
{% endmacro %}
{% set ns = namespace(count=0) %}
{% for r in recs %}
    {% if r.marker and pclass_filter is none or r.selector.config.pclass_id == pclass_filter %}
        {% set ns.count = ns.count + 1 %}
        {{ marker_tag(r) }}
    {% endif %}
{% endfor %}
{% if ns.count == 0 %}
    <span class="label label-default btn-table-block">None</span>
{% endif %}
{% if overassigned %}
    <div class="has-error">
        <p class="help-block">Marking workload exceeds CATS limit (assigned={{ assigned }}, max capacity={{ lim }})</p>
    </div>
{% endif %}
"""


_workload = \
"""
<span class="label {% if sup_overassigned %}label-danger{% else %}label-info{% endif %}">S {{ sup }}</span>
<span class="label {% if mark_overassigned %}label-danger{% else %}label-default{% endif %}">M {{ mark }}</span>
<span class="label {% if sup_overassigned or mark_overassigned %}label-danger{% else %}label-primary{% endif %}">Total {{ tot }}</span>
"""


def faculty_view_data(faculty, rec, pclass_filter):

    data = []

    for f in faculty:
        # check for CATS overassignment
        sup_overassigned, CATS_sup, sup_lim = rec.is_supervisor_overassigned(f)
        mark_overassigned, CATS_mark, mark_lim = rec.is_marker_overassigned(f)
        overassigned = sup_overassigned or mark_overassigned

        if pclass_filter is None:
            workload_sup = CATS_sup
            workload_mark = CATS_mark
            workload_tot = CATS_sup + CATS_mark
        else:
            workload_sup, workload_mark = rec.get_faculty_CATS(f.id, pclass_filter)
            workload_tot = workload_sup + workload_mark

        # check for project overassignment and cache error messages to prevent multiple display
        supv_records = rec.get_supervisor_records(f.id).all()
        mark_records = rec.get_marker_records(f.id).all()

        errors = {}
        proj_overassigned = False
        for item in supv_records:
            if pclass_filter is None or item.selector.config.pclass_id == pclass_filter:
                if item.is_project_overassigned:
                    if item.project_id not in errors:
                        errors[item.project_id] = item.error
        if len(errors) > 0:
            proj_overassigned = True

        err_msgs = errors.values()

        data.append({'name': {'display': render_template_string(_name, f=f, overassigned=overassigned or proj_overassigned),
                              'sortvalue': f.user.last_name + f.user.first_name},
                     'projects': render_template_string(_projects, recs=supv_records,
                                                        overassigned=sup_overassigned, assigned=CATS_sup, lim=sup_lim,
                                                        pclass_filter=pclass_filter, err_msgs=err_msgs),
                     'marking': render_template_string(_marking, recs=mark_records,
                                                       overassigned=mark_overassigned, assigned=CATS_mark, lim=mark_lim,
                                                       pclass_filter=pclass_filter),
                     'workload': {'display': render_template_string(_workload, sup=workload_sup, mark=workload_mark,
                                                                    tot=workload_tot,
                                                                    sup_overassigned=sup_overassigned,
                                                                    mark_overassigned=mark_overassigned),
                                  'sortvalue': CATS_sup + CATS_mark}})

    return jsonify(data)
