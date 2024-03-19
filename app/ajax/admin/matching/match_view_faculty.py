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

from ....models import MatchingAttempt, MatchingRecord, FacultyData, SelectingStudent, ProjectClassConfig, StudentData, User

# language=jinja2
_name = """
<a class="text-decoration-none" href="mailto:{{ f.user.email }}">{{ f.user.name }}</a>
{% if overassigned %}
    <i class="fas fa-exclamation-triangle text-danger"></i>
{% endif %}
<div">
    {% for config in match.config_members %}
        {% if pclass_filter is none or (pclass_filter is not none and config.pclass_id == pclass_filter) %}
            {% set rec = enrollments.get(config.pclass_id) %}
            {% if rec is not none %}
                {% set pcl = rec.pclass %}
                {% set style = pcl.make_CSS_style() %}
                <div class="mt-1 bg-light p-1">
                    <div class="d-flex flex-row justify-content-start align-items-center gap-2">
                        {{ small_swatch(style) }}
                        <span class="small text-secondary text-uppercase">{{ config.abbreviation }}</span>
                    </div>
                    <div class="ms-2"><span class="small text-secondary">Offered: {{ f.number_projects_offered(pcl.id) }}</span></div>
                    <div class="ms-2 d-flex flex-row justify-content-start gap-2 flex-wrap align-items-top">
                        <div>
                            {% if rec.supervisor_state == rec.SUPERVISOR_ENROLLED %}
                                <span class="text-success small"><i class="fas fa-check-circle"></i> Sup</span>
                                {% if rec.CATS_supervision %}
                                    <span class="text-muted small">(<i class="fas fa-arrow-down"></i> {{ rec.CATS_supervision }})</span>
                                {% endif %}
                            {% else %}
                                <span class="text-danger small"><i class="fas fa-times-circle"></i> Sup</span>
                            {% endif %}
                        </div>
                        <div>
                            {% if rec.marker_state == rec.MARKER_ENROLLED %}
                                <span class="text-success small"><i class="fas fa-check-circle"></i> Mark</span>
                                {% if rec.CATS_marking %}
                                    <span class="text-muted small">(<i class="fas fa-arrow-down"></i> {{ rec.CATS_marking }})</span>
                                {% endif %}
                            {% else %}
                                <span class="text-danger small"><i class="fas fa-times-circle"></i> Mark</span>
                            {% endif %}
                        </div>
                        <div>
                            {% if rec.moderator == rec.MODERATOR_ENROLLED %}
                                <span class="text-success small"><i class="fas fa-check-circle"></i> Mod</span>
                                {% if rec.CATS_moderation %}
                                    <span class="text-muted small">(<i class="fas fa-arrow-down"></i> {{ rec.CATS_moderation }})</span>
                                {% endif %}
                            {% else %}
                                <span class="text-danger small"><i class="fas fa-times-circle"></i> Mod</span>
                            {% endif %}
                        </div>
                    </div>
                </div>
            {% endif %}
        {% endif %}
    {% endfor %}
</div>
{% if f.CATS_supervision is not none or f.CATS_marking is not none or f.CATS_moderation is not none %}
    <div class="mt-2 bg-light p-1">
        <div class="small text-secondary text-uppercase">Global limits</div>
        <div class="ms-2 d-flex flex-row justify-content-start gap-2 flex-wrap align-items-top">
            {%- if f.CATS_supervision is not none %}
                <div><span class="text-muted small">Sup <i class="fas fa-arrow-down"></i> {{ f.CATS_supervision }}</span></div>
            {%- endif -%}
            {%- if f.CATS_marking is not none %}
                <div><span class="text-muted small">Mark <i class="fas fa-arrow-down"></i> {{ f.CATS_marking }}</span></div>
            {%- endif -%}
            {%- if f.CATS_moderation is not none %}
                <div><span class="text-muted small">Mod <i class="fas fa-arrow-down"></i> {{ f.CATS_moderation }}</span></div>
            {%- endif -%}
        </div>
    </div>
{% endif %}
"""


# language=jinja2
_projects = """
{% set ns = namespace(count=0) %}
<div class="d-flex flex-column gap-1 justify-content-start align-items-start">
    {% for config_key, bin in recs|dictsort %}
        {% if bin|length > 0 and (pclass_filter is none or config_key[1] == pclass_filter) %}
            <div class="mt-1 text-secondary text-uppercase">{{ config_key[0] }}</div>
            {% for key, r in bin|dictsort %}
                {% set ns.count = ns.count + 1 %}
                {{ project_tag(r, true, 2, url_for('admin.match_faculty_view', id=r.matching_id)) }}
            {% endfor %}
        {% endif %}
    {% endfor %}
    {% if ns.count == 0 %}
        <span class="text-danger"><i class="fas fa-ban"></i> None</span>
    {% endif %}
</div>
{{ error_block_inline(err_msgs, warn_msgs) }}
"""


# language=jinja2
_marking = """
{% set ns = namespace(count=0) %}
<div class="d-flex flex-column gap-1 justify-content-start align-items-start">
    {% for config_key, bin in recs|dictsort %}
        {% if bin|length > 0 and (pclass_filter is none or config_key[1] == pclass_filter) %}
            <div class="mt-1 text-secondary text-uppercase">{{ config_key[0] }}</div>
            {% for key, r in bin|dictsort %}
                {% set ns.count = ns.count + 1 %}
                {{ faculty_marker_tag(r, true) }}
            {% endfor %}
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


def _make_record_key(rec: MatchingRecord) -> str:
    sel: SelectingStudent = rec.selector
    student: StudentData = sel.student
    user: User = student.user

    key = user.last_name + user.first_name + str(user.id)
    return key


def faculty_view_data(faculty: List[FacultyData], match_attempt: MatchingAttempt, pclass_filter, type_filter, hint_filter, show_includes):
    project_tag = get_template_attribute("admin/matching/project_tag.html", "project_tag")
    faculty_marker_tag = get_template_attribute("admin/matching/marker_tag.html", "faculty_marker_tag")

    error_block_inline = get_template_attribute("error_block.html", "error_block_inline")
    small_swatch = get_template_attribute("swatch.html", "small_swatch")

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
        for record_key in included_sup:
            if record_key in included_mark:
                included_workload[record_key] = included_sup[record_key] + included_mark[record_key]

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

        # apply filters if any are present
        if len(filter_list) > 0:
            supv_records = [x for x in supv_records if all(f(x) for f in filter_list)]

        supv_binned = {}
        mark_binned = {}

        # FOR EACH INCLUDED PROJECT CLASS, FACULTY ASSIGNMENTS SHOULD RESPECT ANY CUSTOM CATS LIMITS
        enrolments = {}
        for config in match_attempt.config_members:
            rec = f.get_enrollment_record(config.pclass_id)
            enrolments[config.pclass_id] = rec

            # set up empty bins for supervisor and marker records; these will be populated later
            config_key = (config.name, config.pclass_id)
            supv_binned[config_key] = {}
            mark_binned[config_key] = {}

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

        # BIN SUPERVISOR AND MARKER ASSIGNMENTS BY PROJECT CLASS
        for rec in supv_records:
            rec: MatchingRecord
            config: ProjectClassConfig = rec.selector.config
            config_key = (config.name, config.pclass_id)
            record_key = _make_record_key(rec)
            supv_binned[config_key].update({record_key: rec})

        for rec in mark_records:
            rec: MatchingRecord
            config: ProjectClassConfig = rec.selector.config
            config_key = (config.name, config.pclass_id)
            record_key = _make_record_key(rec)
            mark_binned[config_key].update({record_key: rec})

        sup_err_msgs = sup_errors.values()
        mark_err_msgs = mark_errors.values()

        sup_warn_msgs = sup_warnings.values()
        mark_warn_msgs = mark_warnings.values()

        return {
            "name": render_template(
                name_templ,
                f=f,
                overassigned=overassigned,
                match=match_attempt,
                enrollments=enrolments,
                pclass_filter=pclass_filter,
                small_swatch=small_swatch,
            ),
            "projects": render_template(
                projects_templ,
                recs=supv_binned,
                pclass_filter=pclass_filter,
                err_msgs=sup_err_msgs,
                warn_msgs=sup_warn_msgs,
                project_tag=project_tag,
                error_block_inline=error_block_inline,
            ),
            "marking": render_template(
                marking_templ,
                recs=mark_binned,
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
