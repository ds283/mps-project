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
    <div class="{% if adjustable %}dropdown{% else %}disabled{% endif %} match-assign-button" style="display: inline-block;">
        <a class="label {% if proj_overassigned %}label-danger{% elif style %}label-default{% else %}label-info{% endif %} btn-table-block {% if adjustable %}dropdown-toggle{% endif %}"
                {% if not proj_overassigned and style %}style="{{ style }}"{% endif %}
                {% if adjustable %}type="button" data-toggle="dropdown"{% endif %}>#{{ r.submission_period }}:
            {{ r.selector.student.user.name }} (No. {{ r.project.number }})
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
<span class="label {% if sup_overassigned or mark_overassigned %}label-danger{% else %}label-primary{% endif %}">T {{ tot }}</span>
{% if m.include_matches.count() > 0 and included_sup_CATS is not none and included_mark_CATS is not none and included_workload_CATS is not none %}
    <p></p>
    {% for match in m.include_matches %}
        <span class="label label-info">{{ match.name }} S {{ included_sup_CATS[match.id] }} M {{ included_mark_CATS[match.id] }} T {{ included_workload_CATS[match.id] }}</span>
    {% endfor %}
    <p></p>
    <span class="label {% if sup_overassigned or mark_overassigned %}label-danger{% else %}label-primary{% endif %}">Total {{ total_CATS_value }}</span>
{% endif %}
"""


def faculty_view_data(faculty, match_attempt, pclass_filter, show_includes):
    data = []

    for f in faculty:
        sup_errors = {}
        mark_errors = {}

        # check for CATS overassignment
        sup_overassigned, CATS_sup, included_sup, sup_lim, sup_msg = \
            match_attempt.is_supervisor_overassigned(f, include_matches=show_includes, pclass_id=pclass_filter)
        mark_overassigned, CATS_mark, included_mark, mark_lim, mark_msg = \
            match_attempt.is_marker_overassigned(f, include_matches=show_includes, pclass_id=pclass_filter)

        if sup_overassigned:
            sup_errors['sup_over'] = sup_msg
        if mark_overassigned:
            mark_errors['mark_over'] = mark_msg
        overassigned = sup_overassigned or mark_overassigned

        if show_includes:
            this_sup, this_mark = match_attempt.get_faculty_CATS(f, pclass_id=pclass_filter)
        else:
            this_sup = CATS_sup
            this_mark = CATS_mark

        if pclass_filter is not None:
            _sup_overassigned, _CATS_sup, _included_sup, _sup_lim, _sup_msg = \
                match_attempt.is_supervisor_overassigned(f, include_matches=show_includes)
            _mark_overassigned, _CATS_mark, _included_mark, _mark_lim, _mark_msg = \
                match_attempt.is_marker_overassigned(f, include_matches=show_includes)

            if _sup_overassigned:
                sup_errors['sup_over_full'] = _sup_msg
            if _mark_overassigned:
                mark_errors['mark_over_full'] = _mark_msg
            overassigned = overassigned or _sup_overassigned or _mark_overassigned

        included_workload = {}
        for key in included_sup:
            if key in included_mark:
                included_workload[key] = included_sup[key] + included_mark[key]

        supv_records = match_attempt.get_supervisor_records(f.id).all()
        mark_records = match_attempt.get_marker_records(f.id).all()

        for item in supv_records:
            if pclass_filter is None or item.selector.config.pclass_id == pclass_filter:
                flag, msg = match_attempt.is_project_overassigned(item.project)
                if flag:
                    if item.project_id not in sup_errors:
                        sup_errors[item.project_id] = msg
        proj_overassigned = len(sup_errors) > 0
        overassigned = overassigned or proj_overassigned

        sup_err_msgs = sup_errors.values()
        mark_err_msgs = mark_errors.values()

        data.append({'name': {'display': render_template_string(_name, f=f, overassigned=overassigned),
                              'sortvalue': f.user.last_name + f.user.first_name},
                     'projects': {'display': render_template_string(_projects, recs=supv_records,
                                                                    pclass_filter=pclass_filter, err_msgs=sup_err_msgs),
                                  'sortvalue': len(supv_records)},
                     'marking': {'display': render_template_string(_marking, recs=mark_records,
                                                                   pclass_filter=pclass_filter, err_msgs=mark_err_msgs),
                                 'sortvalue': len(mark_records)},
                     'workload': {'display': render_template_string(_workload, m=match_attempt,
                                                                    sup=this_sup, mark=this_mark,
                                                                    tot=this_sup + this_mark,
                                                                    sup_overassigned=sup_overassigned,
                                                                    mark_overassigned=mark_overassigned,
                                                                    included_sup_CATS=included_sup,
                                                                    included_mark_CATS=included_mark,
                                                                    included_workload_CATS=included_workload,
                                                                    total_CATS_value=CATS_sup + CATS_mark),
                                  'sortvalue': CATS_sup + CATS_mark}})

    return jsonify(data)
