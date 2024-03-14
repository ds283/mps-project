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

from flask import render_template, current_app, get_template_attribute
from jinja2 import Template, Environment

from ....models import MatchingAttempt, MatchingRecord, FacultyData

# language=jinja2
_name = """
<a class="text-decoration-none" href="mailto:{{ f.user.email }}">{{ f.user.name }}</a>
{% if overassigned %}
    <i class="fas fa-exclamation-triangle text-danger"></i>
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
_projects = """
{% set ns = namespace(count=0) %}
<div class="d-flex flex-column gap-1 justify-content-start align-items-start">
    {% for r in recs %}
        {% if pclass_filter is none or r.selector.config.pclass_id == pclass_filter %}
            {% set ns.count = ns.count + 1 %}
            {{ project_tag(r, true, 2, url_for('admin.match_faculty_view', id=r.matching_id)) }}
        {% endif %}
    {% endfor %}
    {% if ns.count == 0 %}
        <span class="badge bg-secondary btn-table-block">None</span>
    {% endif %}
</div>
{{ error_block_inline(err_msgs, warn_msgs) }}
"""


# language=jinja2
_marking = """
{% set ns = namespace(count=0) %}
<div class="d-flex flex-column gap-1 justify-content-start align-items-start">
    {% for r in recs %}
        {% if pclass_filter is none or r.selector.config.pclass_id == pclass_filter %}
            {% set ns.count = ns.count + 1 %}
            {{ faculty_marker_tag(r, true) }}
        {% endif %}
    {% endfor %}
    {% if ns.count == 0 %}
        <span class="badge bg-secondary btn-table-block">None</span>
    {% endif %}
</div>
{{ error_block_inline(err_msgs, warn_msgs) }}
"""


# language=jinja2
_workload = """
<div class="small">
    {% if sup_overassigned %}<span class="text-danger"><i class="fas fa-exclamation-triangle"></i></span>{% endif %}
    <span class="text-secondary">Supervising</span> <strong>{{ sup }}</strong>
</div>
<div class="small">
    {% if mark_overassigned %}<span class="text-danger"><i class="fas fa-exclamation-triangle"></i></span>{% endif %}
    <span class="text-secondary">Marking</span> <strong>{{ mark }}</strong>
</div>
<div class="small mt-1">
    <span class="text-primary">Total <strong>{{ tot }}</strong></span>
</div>
{% if included_sup is not none and included_mark is not none and included_workload is not none and included_workload|length > 0 %}
    <hr>
    <div class="small text-muted">INCLUDED MATCHES</div>
    {% for match in m.include_matches %}
        <div class="small mt-1"><strong>{{ match.name }}</strong></div>
        <div class="small">
            S {{ included_sup[match.id] }} M {{ included_mark[match.id] }} T {{ included_workload[match.id] }}
        </div>
    {% endfor %}
    <div class="small mt-1">
        <strong>Total included</strong>: {{ total_CATS_value }}
    </div>
{% endif %}
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_projects_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_projects)


def _build_marking_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_marking)


def _build_workload_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_workload)


def faculty_view_data(faculty: List[FacultyData], match_attempt: MatchingAttempt, pclass_filter, type_filter, hint_filter, show_includes):
    project_tag = get_template_attribute("admin/matching/project_tag.html", "project_tag")
    faculty_marker_tag = get_template_attribute("admin/matching/marker_tag.html", "faculty_marker_tag")

    error_block_inline = get_template_attribute("error_block.html", "error_block_inline")

    name_templ: Template = _build_name_templ()
    projects_templ: Template = _build_projects_templ()
    marking_templ: Template = _build_marking_templ()
    workload_templ: Template = _build_workload_templ()

    def _data(f: FacultyData):
        sup_errors = {}
        mark_errors = {}

        sup_warnings = {}
        mark_warnings = {}

        # check for CATS overassignment
        payload = match_attempt.is_supervisor_overassigned(f, include_matches=show_includes, pclass_id=pclass_filter)
        sup_overassigned = payload.get("flag", False)
        CATS_sup = payload.get("CATS_total", None)
        included_sup = payload.get("included", {})
        sup_msg = payload.get("error_message", None)

        payload = match_attempt.is_marker_overassigned(f, include_matches=show_includes, pclass_id=pclass_filter)
        mark_overassigned = payload.get("flag", False)
        CATS_mark = payload.get("CATS_total", None)
        included_mark = payload.get("included", {})
        mark_msg = payload.get("error_message", None)

        if sup_overassigned:
            sup_errors["sup_over"] = sup_msg
        if mark_overassigned:
            mark_errors["mark_over"] = mark_msg
        overassigned = sup_overassigned or mark_overassigned

        if show_includes:
            this_sup, this_mark, this_mod = match_attempt.get_faculty_CATS(f, pclass_id=pclass_filter)
        else:
            this_sup = CATS_sup
            this_mark = CATS_mark

        if pclass_filter is not None:
            payload = match_attempt.is_supervisor_overassigned(f, include_matches=show_includes)
            _sup_overassigned = payload.get("flag", False)
            _CATS_sup = payload.get("CATS_total", None)
            _sup_msg = payload.get("error_message", None)

            payload = match_attempt.is_marker_overassigned(f, include_matches=show_includes)
            _mark_overassigned = payload.get("flag", False)
            _CATS_mark = payload.get("CATS_total", None)
            _mark_msg = payload.get("error_message", None)

            if _sup_overassigned:
                sup_errors["sup_over_full"] = _sup_msg
            if _mark_overassigned:
                mark_errors["mark_over_full"] = _mark_msg
            overassigned = overassigned or _sup_overassigned or _mark_overassigned

        included_workload = {}
        for key in included_sup:
            if key in included_mark:
                included_workload[key] = included_sup[key] + included_mark[key]

        supv_records: List[MatchingRecord] = match_attempt.get_supervisor_records(f.id).all()
        mark_records: List[MatchingRecord] = match_attempt.get_marker_records(f.id).all()

        filter_list = []

        if type_filter == "ordinary":

            def filt(r: MatchingRecord):
                return not r.project.generic

            filter_list.append(filt)

        elif type_filter == "generic":

            def filt(r: MatchingRecord):
                return r.project.generic

            filter_list.append(filt)

        if hint_filter == "satisfied":

            def filt(r: MatchingRecord):
                return len(r.hint_status[0]) > 0

            filter_list.append(filt)

        elif hint_filter == "violated":

            def filt(r: MatchingRecord):
                return len(r.hint_status[1]) > 0

            filter_list.append(filt)

        if len(filter_list) > 0:
            supv_records = [x for x in supv_records if all(f(x) for f in filter_list)]

        # FOR EACH INCLUDED PROJECT CLASS, FACULTY ASSIGNMENTS SHOULD RESPECT ANY CUSTOM CATS LIMITS
        enrollments = {}
        for config in match_attempt.config_members:
            rec = f.get_enrollment_record(config.pclass_id)
            enrollments[config.pclass_id] = rec

            if rec is None:
                continue

            sup, mark, mod = match_attempt.get_faculty_CATS(f, pclass_id=config.pclass_id)

            if rec.CATS_supervision is not None and sup > rec.CATS_supervision:
                sup_errors[("custom_sup", f.id)] = "Assignment to {name} violates custom supervising CATS limit {n}".format(
                    name=f.user.name, n=rec.CATS_supervision
                )
                overassigned = True
                sup_overassigned = True

            if rec.CATS_marking is not None and mark > rec.CATS_marking:
                mark_errors[("custom_mark", f.id)] = "Assignment to {name} violates custom marking CATS limit {n}".format(
                    name=f.user.name, n=rec.CATS_marking
                )
                overassigned = True
                mark_overassigned = True

            # TODO: UPDATE MODERATE CATS

        sup_err_msgs = sup_errors.values()
        mark_err_msgs = mark_errors.values()

        sup_warn_msgs = sup_warnings.values()
        mark_warn_msgs = mark_warnings.values()

        return {
            "name": render_template(
                name_templ, f=f, overassigned=overassigned, match=match_attempt, enrollments=enrollments, pclass_filter=pclass_filter
            ),
            "projects": render_template(
                projects_templ,
                recs=supv_records,
                pclass_filter=pclass_filter,
                err_msgs=sup_err_msgs,
                warn_msgs=sup_warn_msgs,
                project_tag=project_tag,
                error_block_inline=error_block_inline,
            ),
            "marking": render_template(
                marking_templ,
                recs=mark_records,
                pclass_filter=pclass_filter,
                err_msgs=mark_err_msgs,
                warn_msgs=mark_warn_msgs,
                faculty_marker_tag=faculty_marker_tag,
                error_block_inline=error_block_inline,
            ),
            "workload": render_template(
                workload_templ,
                m=match_attempt,
                sup=this_sup,
                mark=this_mark,
                tot=this_sup + this_mark,
                sup_overassigned=sup_overassigned,
                mark_overassigned=mark_overassigned,
                included_sup=included_sup,
                included_mark=included_mark,
                included_workload=included_workload,
                total_CATS_value=CATS_sup + CATS_mark,
            ),
        }

    return [_data(f) for f in faculty]
