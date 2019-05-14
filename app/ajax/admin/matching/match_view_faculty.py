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

from ....shared.utils import get_count


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
    {% if r.selector.has_submission_list %}{% set adjustable = true %}{% endif %}
    {% set pclass = r.selector.config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    {% set proj_overassigned = r.is_project_overassigned %}
    <div>
        <div class="{% if adjustable %}dropdown{% else %}disabled{% endif %} match-assign-button" style="display: inline-block;">
            <a class="label {% if proj_overassigned %}label-danger{% elif style %}label-default{% else %}label-info{% endif %} btn-table-block {% if adjustable %}dropdown-toggle{% endif %}"
                    {% if not proj_overassigned and style %}style="{{ style }}"{% endif %}
                    {% if adjustable %}type="button" data-toggle="dropdown"{% endif %}>#{{ r.submission_period }}:
                {{ r.selector.student.user.name }} (No. {{ r.project.number }})
            {% if adjustable %}<span class="caret"></span>{% endif %}</a>
            {% if adjustable %}
                {% set list = r.selector.ordered_selections %}
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
{% if err_msgs|length > 0 %}
    <div class="has-error">
        {% for msg in err_msgs %}
            <p class="help-block">{{ msg }}</p>
        {% endfor %}
    </div>
{% endif %}
"""


_workload = \
"""
<span class="label {% if sup_overassigned %}label-danger{% else %}label-info{% endif %}">S {{ sup }}</span>
<span class="label {% if mark_overassigned %}label-danger{% else %}label-default{% endif %}">M {{ mark }}</span>
<span class="label {% if sup_overassigned or mark_overassigned %}label-danger{% else %}label-primary{% endif %}">Total {{ tot }}</span>
{% if m.include_matches.count() > 0 and include_sup_CATS is not none and include_mark_CATS is not none and include_workload_CATS is not none %}
    <p></p>
    {% for match in m.include_matches %}
        <span class="label label-primary">{{ match.name }}</span>
        <span class="label label-info">S {{ included_sup_CATS[match.id] }}</span>
        <span class="label label-default">M {{ included_mark_CATS[match.id] }}</span>
        <span class="label label-primary">Total {{ included_workload_CATS[match.id] }}</span>
    {% endfor %}
    <p></p>
    <span class="label label-primary">Grand total: {{ total_CATS_value }}</span>
{% endif %}
"""


def faculty_view_data(faculty, match_attempt, pclass_filter, show_includes):
    data = []

    for f in faculty:
        sup_errors = {}
        mark_errors = {}

        # check for CATS overassignment
        sup_overassigned, CATS_sup, sup_lim, sup_msg = match_attempt.is_supervisor_overassigned(f)
        mark_overassigned, CATS_mark, mark_lim, mark_msg = match_attempt.is_marker_overassigned(f)

        included_sup_CATS = None
        included_mark_CATS = None
        included_workload_CATS = None

        if show_includes and get_count(match_attempt.include_matches) > 0:
            included_sup_CATS = {}
            included_mark_CATS = {}
            included_workload_CATS = {}

            for match in match_attempt.include_matches:
                sup, mark = match.get_faculty_CATS(f, pclass_id=pclass_filter)

                included_sup_CATS[match.id] = sup
                included_mark_CATS[match.id] = mark
                included_workload_CATS[match.id] = sup + mark

            total_sup = CATS_sup + sum(included_sup_CATS.values())
            total_mark = CATS_mark + sum(included_mark_CATS.values())

            sup_overassigned = total_sup > sup_lim
            mark_overassigned = total_mark > mark_lim

            if sup_overassigned and sup_msg is None:
                sup_msg = 'Supervising workload for {name} exceeds CATS limit after inclusion of all matches ' \
                          '(assigned={m}, max capacity={n})'.format(name=f.user.name, m=total_sup, n=sup_lim)

            if mark_overassigned and mark_msg is None:
                mark_msg = 'Marking workload for {name} exceeds CATS limit ' \
                           '(assigned={m}, max capacity={n})'.format(name=f.user.name, m=total_mark, n=mark_lim)

        if sup_overassigned:
            sup_errors['sup_over'] = sup_msg
        if mark_overassigned:
            mark_errors['mark_over'] = mark_msg

        if pclass_filter is None:
            workload_sup = CATS_sup
            workload_mark = CATS_mark
            workload_tot = CATS_sup + CATS_mark
        else:
            workload_sup, workload_mark = match_attempt.get_faculty_CATS(f.id, pclass_filter)
            workload_tot = workload_sup + workload_mark

        # check for project overassignment and cache error messages to prevent multiple display
        supv_records = match_attempt.get_supervisor_records(f.id).all()
        mark_records = match_attempt.get_marker_records(f.id).all()

        for item in supv_records:
            if pclass_filter is None or item.selector.config.pclass_id == pclass_filter:
                flag, msg = match_attempt.is_project_overassigned(item.project)
                if flag:
                    if item.project_id not in sup_errors:
                        sup_errors[item.project_id] = msg
        proj_overassigned = len(sup_errors) > 0
        overassigned = sup_overassigned or mark_overassigned or proj_overassigned

        sup_err_msgs = sup_errors.values()
        mark_err_msgs = mark_errors.values()

        total_CATS_value = workload_tot
        if included_workload_CATS is not None:
            total_CATS_value += sum(included_workload_CATS.values())

        data.append({'name': {'display': render_template_string(_name, f=f, overassigned=overassigned),
                              'sortvalue': f.user.last_name + f.user.first_name},
                     'projects': render_template_string(_projects, recs=supv_records,
                                                        pclass_filter=pclass_filter, err_msgs=sup_err_msgs),
                     'marking': render_template_string(_marking, recs=mark_records,
                                                       pclass_filter=pclass_filter, err_msgs=mark_err_msgs),
                     'workload': {'display': render_template_string(_workload, m=match_attempt,
                                                                    sup=workload_sup, mark=workload_mark,
                                                                    tot=workload_tot,
                                                                    sup_overassigned=sup_overassigned,
                                                                    mark_overassigned=mark_overassigned,
                                                                    included_sup_CATS=included_sup_CATS,
                                                                    included_mark_CATS=included_mark_CATS,
                                                                    included_workload_CATS=included_workload_CATS,
                                                                    total_CATS_value=total_CATS_value),
                                  'sortvalue': total_CATS_value}})

    return jsonify(data)
