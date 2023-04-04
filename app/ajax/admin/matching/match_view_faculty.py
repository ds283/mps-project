#
# Created by David Seery on 22/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import List

from flask import jsonify, render_template_string

from ....models import MatchingAttempt, MatchingRecord

# language=jinja2
_name = \
"""
<a class="text-decoration-none" href="mailto:{{ f.user.email }}">{{ f.user.name }}</a>
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
                <span class="badge {% if style is not none %}bg-secondary{% else %}bg-info{% endif %}" {% if style is not none %}style="{{ style }}"{% endif %}>
                    {{ pcl.abbreviation }}
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
                {% if rec.CATS_supervision is not none or rec.CATS_marking is not none or rec.CATS_moderation is not none %}
                    {% set style = pcl.make_CSS_style() %}
                    <span class="badge {% if style is not none %}bg-secondary{% else %}bg-info{% endif %}" {% if style is not none %}style="{{ style }}"{% endif %}>
                        {{ pcl.abbreviation }}
                        {%- if rec.CATS_supervision is not none %}
                            S {{ rec.CATS_supervision }}
                        {%- endif -%}
                        {%- if rec.CATS_marking is not none %}
                            Mk {{ rec.CATS_marking }}
                        {%- endif -%}
                        {%- if rec.cats_moderation is not none %}
                            Mo {{ rec.CATS_moderation }}
                        {%- endif -%}
                    </span>
                {% endif %}
            {% endif %}
        {% endif %}
    {% endfor %}
    {% if f.CATS_supervision is not none or f.CATS_marking is not none or f.CATS_moderation is not none %}
        <span class="badge bg-primary">
            Global
            {%- if f.CATS_supervision is not none %}
                S {{ f.CATS_supervision }}
            {%- endif -%}
            {%- if f.CATS_marking is not none %}
                Mk {{ f.CATS_marking }}
            {%- endif -%}
            {%- if f.CATS_moderation is not none %}
                Mo {{ f.CATS_moderation }}
            {%- endif -%}
        </span>
    {% endif %}
</div>
"""


# language=jinja2
_projects = \
"""
{% macro truncate_name(name, maxlength=25) %}
    {%- if name|length > maxlength -%}
        {{ name[0:maxlength] }}...
    {%- else -%}
        {{ name }}
    {%- endif -%}
{% endmacro %}
{% macro project_tag(r) %}
    {% set adjustable = false %}
    {% if r.selector.has_submission_list %}{% set adjustable = true %}{% endif %}
    {% set pclass = r.selector.config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    {% set has_issues = r.has_issues %}
    <div class="{% if adjustable %}dropdown{% else %}disabled{% endif %} match-assign-button" style="display: inline-block;">
        <a class="badge text-decoration-none text-nohover-light {% if has_issues %}bg-danger{% elif style %}bg-secondary{% else %}bg-info{% endif %} btn-table-block {% if adjustable %}dropdown-toggle{% endif %}"
                {% if not has_issues and style %}style="{{ style }}"{% endif %}
                {% if adjustable %}data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false"{% endif %}>
            #{{ r.submission_period }}: {{ r.selector.student.user.last_name }} ({{ truncate_name(r.project.name) }})
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
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.reassign_supervisor_roles', rec_id=r.id, url=url_for('admin.match_faculty_view', id=r.matching_id)) }}">
                    Edit supervisor roles...
                </a>                
            </div>
        {% endif %}
    </div>
    {% if r.project.generic %}
        <span class="badge bg-info">GENERIC</span>
    {% endif %}
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
{% endmacro %}
{% set ns = namespace(count=0) %}
{% for r in recs %}
    {% if pclass_filter is none or r.selector.config.pclass_id == pclass_filter %}
        {% set ns.count = ns.count + 1 %}
        {{ project_tag(r) }}
    {% endif %}
{% endfor %}
{% if ns.count == 0 %}
    <span class="badge bg-secondary btn-table-block">None</span>
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
{% macro truncate_name(name, maxlength=25) %}
    {%- if name|length > maxlength -%}
        {{ name[0:maxlength] }}...
    {%- else -%}
        {{ name }}
    {%- endif -%}
{% endmacro %}
{% macro marker_tag(r) %}
    {% set pclass = r.selector.config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    <div class="badge {% if style %}bg-secondary{% else %}bg-info{% endif %} btn-table-block" {% if style %}style="{{ style }}"{% endif %}>
        #{{ r.submission_period }}: {{ r.selector.student.user.last_name }} ({{ truncate_name(r.project.name) }})
    </div>
    {# <div class="dropdown match-assign-button" style="display: inline-block;">
        <a class="badge text-decoration-none text-nohover-light {% if style %}bg-secondary{% else %}bg-info{% endif %} btn-table-block dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} data-bs-toggle="dropdown"
            href="" role="button" aria-haspopup="true" aria-expanded="false">
            #{{ r.submission_period }}: {{ r.selector.student.user.name }} (No. {{ r.project.number }})
        </a>
        <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
            <div class="dropdown-header">Reassign marker</div>
            {% set assessor_list = r.project.assessor_list %}
            {% for marker in assessor_list %}
                {% set disabled = false %}
                {% if marker.id == r.marker_id %}{% set disabled = true %}{% endif %}
                <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.reassign_match_marker', id=r.id, mid=marker.id) }}"{% endif %}>
                    {{ marker.user.name }}
                </a>
            {% endfor %}
        </div>
    </div> #}
{% endmacro %}
{% set ns = namespace(count=0) %}
{% for r in recs %}
    {% if pclass_filter is none or r.selector.config.pclass_id == pclass_filter %}
        {% set ns.count = ns.count + 1 %}
        {{ marker_tag(r) }}
    {% endif %}
{% endfor %}
{% if ns.count == 0 %}
    <span class="badge bg-secondary btn-table-block">None</span>
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
<span class="badge {% if sup_overassigned %}bg-danger{% else %}bg-info{% endif %}">S {{ sup }}</span>
<span class="badge {% if mark_overassigned %}bg-danger{% else %}bg-secondary{% endif %}">M {{ mark }}</span>
<span class="badge {% if sup_overassigned or mark_overassigned %}bg-danger{% else %}bg-primary{% endif %}">T {{ tot }}</span>
{% if included_sup is not none and included_mark is not none and included_workload is not none and included_workload|length > 0 %}
    <p></p>
    {% for match in m.include_matches %}
        <span class="badge bg-info text-dark">{{ match.name }} S {{ included_sup[match.id] }} M {{ included_mark[match.id] }} T {{ included_workload[match.id] }}</span>
    {% endfor %}
    <p></p>
    <span class="badge {% if sup_overassigned or mark_overassigned %}bg-danger{% else %}bg-primary{% endif %}">Total {{ total_CATS_value }}</span>
{% endif %}
"""


def faculty_view_data(faculty, match_attempt: MatchingAttempt, pclass_filter, type_filter, hint_filter, show_includes):
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
            this_sup, this_mark, this_mod = match_attempt.get_faculty_CATS(f, pclass_id=pclass_filter)
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

        supv_records: List[MatchingRecord] = match_attempt.get_supervisor_records(f.id).all()
        mark_records: List[MatchingRecord] = match_attempt.get_marker_records(f.id).all()

        filter_list = []

        if type_filter == 'ordinary':
            def filt(r: MatchingRecord):
                return not r.project.generic

            filter_list.append(filt)

        elif type_filter == 'generic':
            def filt(r: MatchingRecord):
                return r.project.generic

            filter_list.append(filt)

        if hint_filter == 'satisfied':
            def filt(r: MatchingRecord):
                return len(r.hint_status[0]) > 0

            filter_list.append(filt)

        elif hint_filter == 'violated':
            def filt(r: MatchingRecord):
                return len(r.hint_status[1]) > 0

            filter_list.append(filt)

        if len(filter_list) > 0:
            supv_records = [x for x in supv_records if all(f(x) for f in filter_list)]

            if len(supv_records) == 0:
                continue

        # FOR EACH INCLUDED PROJECT CLASS, FACULTY ASSIGNMENTS SHOULD RESPECT ANY CUSTOM CATS LIMITS
        enrollments = {}
        for config in match_attempt.config_members:
            rec = f.get_enrollment_record(config.pclass_id)
            enrollments[config.pclass_id] = rec

            if rec is None:
                continue

            sup, mark, mod = match_attempt.get_faculty_CATS(f, pclass_id=config.pclass_id)

            if rec.CATS_supervision is not None and sup > rec.CATS_supervision:
                sup_errors[('custom_sup', f.id)] = 'Assignment to {name} violates custom supervising CATS ' \
                                                   'limit {n}'.format(name=f.user.name, n=rec.CATS_supervision)
                overassigned = True
                sup_overassigned = True

            if rec.CATS_marking is not None and mark > rec.CATS_marking:
                mark_errors[('custom_mark', f.id)] = 'Assignment to {name} violates custom marking CATS ' \
                                                     'limit {n}'.format(name=f.user.name, n=rec.CATS_marking)
                overassigned = True
                mark_overassigned = True

            # TODO: UPDATE MODERATE CATS

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
