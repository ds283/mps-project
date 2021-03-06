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


# language=jinja2
_name = \
"""
<a href="mailto:{{ f.user.email }}">{{ f.user.name }}</a>
{% if overassigned %}
    <i class="fas fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
<div>
    {% for config in match.config_members %}
        {% if pclass_filter is none or (pclass_filter is not none and config.pclass_id == pclass_filter) %}
            {% set rec = enrollments.get(config.pclass_id) %}
            {% if rec is not none %}
                {% set pcl = rec.pclass %}
                {% set style = pcl.make_CSS_style() %}
                <span class="badge {% if style is not none %}badge-secondary{% else %}badge-info{% endif %}" {% if style is not none %}style="{{ style }}"{% endif %}>{{ pcl.abbreviation }}
                    {{ f.number_projects_offered(pcl.id) }}
                    {%- if rec.supervisor_state == rec.SUPERVISOR_ENROLLED %}
                        S <i class="fas fa-check"></i>
                    {%- else %}
                        S <i class="fas fa-times"></i>
                    {%- endif -%}
                    {%- if rec.marker_state == rec.MARKER_ENROLLED %}
                        M <i class="fas fa-check"></i>
                    {%- else %}
                        M <i class="fas fa-times"></i>
                    {%- endif -%}
                </span>
            {% endif %}
        {% endif %}
    {% endfor %}
</div>
<div>
    {% for config in match.config_members %}
        {% if pclass_filter is none or (pclass_filter is not none and config.pclass_id == pclass_filter) %}
            {% set rec = enrollments.get(config.pclass_id) %}
            {% if rec is not none %}
                {% set pcl = rec.pclass %}
                {% if rec.CATS_supervision is not none or rec.CATS_marking is not none %}
                    {% set style = pcl.make_CSS_style() %}
                    <span class="badge {% if style is not none %}badge-secondary{% else %}badge-info{% endif %}" {% if style is not none %}style="{{ style }}"{% endif %}>{{ pcl.abbreviation }}
                        {%- if rec.CATS_supervision is not none %}
                            S {{ rec.CATS_supervision }}
                        {%- endif -%}
                        {%- if rec.CATS_marking is not none %}
                            M {{ rec.CATS_marking }}
                        {%- endif -%}
                    </span>
                {% endif %}
            {% endif %}
        {% endif %}
    {% endfor %}
    {% if f.CATS_supervision is not none or f.CATS_marking is not none %}
        <span class="badge badge-primary">Global
            {%- if f.CATS_supervision is not none %}
                S {{ f.CATS_supervision }}
            {%- endif -%}
            {%- if f.CATS_marking is not none %}
                M {{ f.CATS_marking }}
            {%- endif -%}
        </span>
    {% endif %}
</div>
"""


# language=jinja2
_projects = \
"""
{% macro project_tag(r) %}
    {% set adjustable = false %}
    {% if r.selector.has_submission_list %}{% set adjustable = true %}{% endif %}
    {% set pclass = r.selector.config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    {% set proj_overassigned = r.is_project_overassigned %}
    <div class="{% if adjustable %}dropdown{% else %}disabled{% endif %} match-assign-button" style="display: inline-block;">
        <a class="badge {% if proj_overassigned %}badge-danger{% elif style %}badge-secondary{% else %}badge-info{% endif %} btn-table-block {% if adjustable %}dropdown-toggle{% endif %}"
                {% if not proj_overassigned and style %}style="{{ style }}"{% endif %}
                {% if adjustable %}data-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false"{% endif %}>#{{ r.submission_period }}:
            {{ r.selector.student.user.name }} (No. {{ r.project.number }})</a>
        {% if adjustable %}
            {% set list = r.selector.ordered_selections %}
            <div class="dropdown-menu">
                <div class="dropdown-header">Submitted choices</div>
                {% for item in list %}
                    {% set disabled = false %}
                    {% if item.liveproject_id == r.project_id or not item.is_selectable %}{% set disabled = true %}{% endif %}
                    <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.reassign_match_project', id=r.id, pid=item.liveproject_id) }}"{% endif %}>
                       #{{ item.rank }}:
                       {{ item.liveproject.owner.user.name }} &ndash; No. {{ item.liveproject.number }}: {{ item.format_project()|safe }} 
                    </a>
                {% endfor %}
            </div>
        {% endif %}
    </div>
    {% set outcome = r.hint_status %}
    {% if outcome is not none %}
        {% set satisfied, violated = outcome %}
        {% if satisfied|length > 0 %}
            <span class="badge badge-success">{%- for i in range(satisfied|length) -%}<i class="fas fa-check"></i>{%- endfor %} HINT</span>
        {% endif %}
        {% if violated|length > 0 %}
            <span class="badge badge-warning">{%- for i in range(violated|length) -%}<i class="fas fa-times"></i>{%- endfor %} HINT</span>
        {% endif %}
    {% endif %}
    {% set prog_status = r.project.satisfies_preferences(r.selector) %}
    {% if prog_status is not none %}
        {% if prog_status %}
            <span class="badge badge-success"><i class="fas fa-check"></i> PROG</span>
        {% else %}
            <span class="badge badge-warning"><i class="fas fa-times"></i> PROG</span>
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
    <span class="badge badge-secondary btn-table-block">None</span>
{% endif %}
{% if err_msgs|length > 0 %}
    <div class="error-block">
        {% for msg in err_msgs %}
            <div class="error-message">{{ msg }}</div>
        {% endfor %}
    </div>
{% endif %}
"""


# language=jinja2
_marking = \
"""
{% macro marker_tag(r) %}
    {% set pclass = r.selector.config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    <div class="dropdown match-assign-button" style="display: inline-block;">
        <a class="badge {% if style %}badge-secondary{% else %}badge-info{% endif %} btn-table-block dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} data-toggle="dropdown"
            role="button" aria-haspopup="true" aria-expanded="false">
            #{{ r.submission_period }}: {{ r.selector.student.user.name }} (No. {{ r.project.number }})
        </a>
        <div class="dropdown-menu">
            <div class="dropdown-header">Reassign 2nd marker</div>
            {% set assessor_list = r.project.assessor_list %}
            {% for marker in assessor_list %}
                {% set disabled = false %}
                {% if marker.id == r.marker_id %}{% set disabled = true %}{% endif %}
                <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.reassign_match_marker', id=r.id, mid=marker.id) }}"{% endif %}>
                    {{ marker.user.name }}
                </a>
            {% endfor %}
        </div>
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
    <span class="badge badge-secondary btn-table-block">None</span>
{% endif %}
{% if err_msgs|length > 0 %}
    <div class="error-block">
        {% for msg in err_msgs %}
            <div class="error-message">{{ msg }}</div>
        {% endfor %}
    </div>
{% endif %}
"""


# language=jinja2
_workload = \
"""
<span class="badge {% if sup_overassigned %}badge-danger{% else %}badge-info{% endif %}">S {{ sup }}</span>
<span class="badge {% if mark_overassigned %}badge-danger{% else %}badge-secondary{% endif %}">M {{ mark }}</span>
<span class="badge {% if sup_overassigned or mark_overassigned %}badge-danger{% else %}badge-primary{% endif %}">T {{ tot }}</span>
{% if included_sup is not none and included_mark is not none and included_workload is not none and included_workload|length > 0 %}
    <p></p>
    {% for match in m.include_matches %}
        <span class="badge badge-info">{{ match.name }} S {{ included_sup[match.id] }} M {{ included_mark[match.id] }} T {{ included_workload[match.id] }}</span>
    {% endfor %}
    <p></p>
    <span class="badge {% if sup_overassigned or mark_overassigned %}badge-danger{% else %}badge-primary{% endif %}">Total {{ total_CATS_value }}</span>
{% endif %}
"""


def faculty_view_data(faculty, match_attempt, pclass_filter, show_includes):
    data = []

    for f in faculty:
        sup_errors = {}
        mark_errors = {}

        # check for CATS overassignment
        payload = match_attempt.is_supervisor_overassigned(f, include_matches=show_includes, pclass_id=pclass_filter)
        sup_overassigned = payload.get('flag', False)
        CATS_sup = payload.get('CATS_total', None)
        included_sup = payload.get('included', {})
        sup_msg = payload.get('error_message', None)

        payload = match_attempt.is_marker_overassigned(f, include_matches=show_includes, pclass_id=pclass_filter)
        mark_overassigned = payload.get('flag', False)
        CATS_mark = payload.get('CATS_total', None)
        included_mark = payload.get('included', {})
        mark_msg = payload.get('error_message', None)

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
            payload = match_attempt.is_supervisor_overassigned(f, include_matches=show_includes)
            _sup_overassigned = payload.get('flag', False)
            _CATS_sup = payload.get('CATS_total', None)
            _sup_msg = payload.get('error_message', None)

            payload = match_attempt.is_marker_overassigned(f, include_matches=show_includes)
            _mark_overassigned = payload.get('flag', False)
            _CATS_mark = payload.get('CATS_total', None)
            _mark_msg = payload.get('error_message', None)

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

        # FOR EACH INCLUDED PROJECT CLASS, FACULTY ASSIGNMENTS SHOULD RESPECT ANY CUSTOM CATS LIMITS
        enrollments = {}
        for config in match_attempt.config_members:
            rec = f.get_enrollment_record(config.pclass_id)
            enrollments[config.pclass_id] = rec

            if rec is None:
                continue

            sup, mark = match_attempt.get_faculty_CATS(f, pclass_id=config.pclass_id)

            if rec.CATS_supervision is not None and sup > rec.CATS_supervision:
                sup_errors[('custom_sup', f.id)] = 'Assignment to {name} violates their custom supervising CATS ' \
                                                   'limit {n}'.format(name=f.user.name, n=rec.CATS_supervision)
                overassigned = True
                sup_overassigned = True

            if rec.CATS_marking is not None and mark > rec.CATS_marking:
                mark_errors[('custom_mark', f.id)] = 'Assignment to {name} violates their custom marking CATS ' \
                                                     'limit {n}'.format(name=f.user.name, n=rec.CATS_marking)
                overassigned = True
                mark_overassigned = True

        sup_err_msgs = sup_errors.values()
        mark_err_msgs = mark_errors.values()

        data.append({'name': {'display': render_template_string(_name, f=f, overassigned=overassigned,
                                                                match=match_attempt, enrollments=enrollments,
                                                                pclass_filter=pclass_filter),
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
                                                                    included_sup=included_sup,
                                                                    included_mark=included_mark,
                                                                    included_workload=included_workload,
                                                                    total_CATS_value=CATS_sup + CATS_mark),
                                  'sortvalue': CATS_sup + CATS_mark}})

    return jsonify(data)
