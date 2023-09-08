#
# Created by David Seery on 2018-11-01.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify
from sqlalchemy.event import listens_for

from ...cache import cache
from ...database import db
from ...models import FacultyData, EnrollmentRecord, SubmissionRecord, ScheduleSlot, LiveProject, ScheduleAttempt, \
    SubmissionRole, ProjectClassConfig, ProjectClass
from ...shared.sqlalchemy import get_count
from ...shared.utils import get_current_year


# language=jinja2
_name = \
"""
<a class="text-decoration-none" href="mailto:{{ f.user.email }}">{{ f.user.name }}</a>
{% if overassigned %}
    <i class="fas fa-exclamation-triangle text-danger"></i>
{% endif %}
"""


# language=jinja2
_groups = \
"""
{% for g in f.affiliations %}
    {{ g.make_label()|safe }}
{% else %}
    <span class="badge bg-secondary">None</span>
{% endfor %}
"""


# language=jinja2
_full_enrollments = \
"""
{%- macro projects_list(projects) -%}
    {%- for p in projects -%}
        <div>{{ loop.index }}. {{ p.name }}</div>
    {%- endfor -%}    
{%- endmacro -%}
{% for record in enrolments %}
    {% set config = configs[record.pclass_id] %}
    <div class="bg-light p-2 mb-2">
        <div class="d-flex flex-row justify-content-start align-items-center gap-2">
            {% set swatch_colour = record.pclass.make_CSS_style() %}
            {% if swatch_colour is not none %}
                <div class="me-1" style="width: 1rem; height: 1rem; {{ swatch_colour|safe }}"></div>
            {% endif %}
            <span>{{ record.pclass.name }}</span>
        </div>
        <div class="d-flex flex-row justify-content-start align-items-center gap-2">
            {% if config.uses_supervisor %}
                <div>
                    {% if record.supervisor_state == record.SUPERVISOR_ENROLLED %}
                        {% set offered = f.number_projects_offered(record.pclass) %}
                        <span class="text-success small">
                            S: enrolled
                        </span>
                        {% if offered == 0 %}
                            <span class="ms-1 small text-danger">No projects</span>
                        {% else %}
                            {% set projects = f.projects_offered(record.pclass) %}
                            <span class="ms-1 small text-muted">
                                {% if offered == 1 %}
                                    1 project
                                {% else %}
                                    {{ offered }} projects
                                {% endif %}
                                <i class="fas fa-info-circle" tabindex="0" data-bs-toggle="popover" title="Projects offered" data-bs-container="body" data-bs-trigger="focus" data-bs-content="{{ projects_list(projects) }}"></i>
                            </span>
                        {% endif %}
                    {% elif record.supervisor_state == record.SUPERVISOR_SABBATICAL %}
                        <span class="text-muted small">
                            S: sabbatical
                            {% if record.supervisor_comment is not none and record.supervisor_comment|length > 0 %}
                                <i class="fas fa-info-circle" tabindex="0" data-bs-toggle="popover" title="Details" data-bs-container="body" data-bs-trigger="focus" data-bs-content="<div>{{ record.supervisor_comment }}</div>{% if record.supervisor_reenroll is not none %}<hr><div class='mt-1'>Re-enrol in {{ record.supervisor_reenroll }}</div>{% endif %}"></i>
                            {% endif %}
                        </span>
                    {% elif record.supervisor_state == record.SUPERVISOR_EXEMPT %}
                        <span class="text-muted small">
                            S: exempt
                            {% if record.supervisor_comment is not none and record.supervisor_comment|length > 0 %}
                                <i class="fas fa-info-circle" tabindex="0" data-bs-toggle="popover" title="Details" data-bs-container="body" data-bs-trigger="focus" data-bs-content="<div>{{ record.supervisor_comment }}</div>{% if record.supervisor_reenroll is not none %}<hr><div class='mt-1'>Re-enrol in {{ record.supervisor_reenroll }}</div>{% endif %}"></i>
                            {% endif %}
                        </span>
                    {% else %}
                        <span class="small text-danger">Supervisor: unknown status</span>
                    {% endif %}
                </div>
            {% endif %}
            {% if config.uses_marker %}
                <div>
                    {% if record.marker_state == record.MARKER_ENROLLED %}
                        <span class="text-success small">
                            Ma: enrolled
                        </span>
                    {% elif record.marker_state == record.MARKER_SABBATICAL %}
                        <span class="text-muted small">
                            Ma: sabbatical
                            {% if record.marker_comment is not none and record.marker_comment|length > 0 %}
                                <i class="fas fa-info-circle" tabindex="1" data-bs-toggle="popover" title="Details" data-bs-container="body" data-bs-trigger="focus" data-bs-content="<div>{{ record.marker_comment }}</div>{% if record.marker_reenroll is not none %}<hr><div class='mt-1'>Re-enrol in {{ record.marker_reenroll }}</div>{% endif %}"></i>
                            {% endif %}
                        </span>
                    {% elif record.marker_state == record.MARKER_EXEMPT %}
                        <span class="text-muted small">
                            Ma: exempt
                            {% if record.marker_comment is not none and record.marker_comment|length > 0 %}
                                    <i class="fas fa-info-circle" tabindex="1" data-bs-toggle="popover" title="Details" data-bs-container="body" data-bs-trigger="focus" data-bs-content="<div>{{ record.marker_comment }}</div>{% if record.marker_reenroll is not none %}<hr><div class='mt-1'>Re-enrol in {{ record.marker_reenroll }}</div>{% endif %}"></i>
                            {% endif %}
                        </span>
                    {% else %}
                        <span class="small text-danger">Marker: unknown status</span>
                    {% endif %}
                </div>
            {% endif %}
            {% if config.uses_moderator %}
                <div>
                    {% if record.moderator_state == record.MARKER_ENROLLED %}
                        <span class="text-success small">
                            Mo: enrolled
                        </span>
                    {% elif record.moderator_state == record.MARKER_SABBATICAL %}
                        <span class="text-muted small">
                            Mo: sabbatical
                            {% if record.moderator_comment is not none and record.moderator_comment|length > 0 %}
                                <i class="fas fa-info-circle" tabindex="2" data-bs-toggle="popover" title="Details" data-bs-container="body" data-bs-trigger="focus" data-bs-content="<div>{{ record.moderator_comment }}</div>{% if record.moderator_reenroll is not none %}<hr><div class='mt-1'>Re-enrol in {{ record.moderator_reenroll }}</div>{% endif %}"></i>
                            {% endif %}
                        </span>
                    {% elif record.moderator_state == record.MARKER_EXEMPT %}
                        <span class="text-muted small">
                            Mo: exempt
                            {% if record.moderator_comment is not none and record.moderator_comment|length > 0 %}
                                    <i class="fas fa-info-circle" tabindex="2" data-bs-toggle="popover" title="Details" data-bs-container="body" data-bs-trigger="focus" data-bs-content="<div>{{ record.moderator_comment }}</div>{% if record.moderator_reenroll is not none %}<hr><div class='mt-1'>Re-enrol in {{ record.moderator_reenroll }}</div>{% endif %}"></i>
                            {% endif %}
                        </span>
                    {% else %}
                        <span class="small text-danger">Moderator: unknown status</span>
                    {% endif %}
                </div>
            {% endif %}
            {% if config.uses_presentations %}
                <div>
                    {% if record.presentations_state == record.MARKER_ENROLLED %}
                        <span class="text-success small">
                            P: enrolled
                        </span>
                    {% elif record.presentations_state == record.MARKER_SABBATICAL %}
                        <span class="text-muted small">
                            P: sabbatical
                            {% if record.presentations_comment is not none and record.presentations_comment|length > 0 %}
                                <i class="fas fa-info-circle" tabindex="3" data-bs-toggle="popover" title="Details" data-bs-container="body" data-bs-trigger="focus" data-bs-content="<div>{{ record.presentations_comment }}</div>{% if record.presentations_reenroll is not none %}<hr><div class='mt-1'>Re-enrol in {{ record.presentations_reenroll }}</div>{% endif %}"></i>
                            {% endif %}
                        </span>
                    {% elif record.presentations_state == record.MARKER_EXEMPT %}
                        <span class="text-muted small">
                            P: exempt
                            {% if record.presentations_comment is not none and record.presentations_comment|length > 0 %}
                                    <i class="fas fa-info-circle" tabindex="3" data-bs-toggle="popover" title="Details" data-bs-container="body" data-bs-trigger="focus" data-bs-content="<div>{{ record.presentations_comment }}</div>{% if record.presentations_reenroll is not none %}<hr><div class='mt-1'>Re-enrol in {{ record.presentations_reenroll }}</div>{% endif %}"></i>
                            {% endif %}
                        </span>
                    {% else %}
                        <span class="small text-danger">Presentations: unknown status</span>
                    {% endif %}
                </div>
            {% endif %}
        </div>
    </div>
{% else %}
    <span class="alert alert-danger p-1"><strong>None</strong></span>
{% endfor %}
"""


# language=jinja2
_simple_enrollments = \
"""
{%- macro projects_list(projects) -%}
    {%- for p in projects -%}
        <div>{{ loop.index }}. {{ p.name }}</div>
    {%- endfor -%}    
{%- endmacro -%}
{% for record in enrolments %}
    {% set config = configs[record.pclass_id] %}
    <div class="bg-light p-1 mb-1">
        <div class="d-flex flex-row justify-content-start align-items-center gap-1">
            {% set swatch_colour = record.pclass.make_CSS_style() %}
            {% if swatch_colour is not none %}
                <div class="me-1" style="width: 1rem; height: 1rem; {{ swatch_colour|safe }}"></div>
            {% endif %}
            {{ record.pclass.name }}
            {% if config.uses_supervisor %}
                {% if record.supervisor_state == record.SUPERVISOR_ENROLLED %}
                    {% set offered = f.number_projects_offered(record.pclass) %}
                    <div>
                        {% if offered == 0 %}
                            <span class="ms-1 small text-danger">No projects</span>
                        {% else %}
                            {% set projects = f.projects_offered(record.pclass) %}
                            <span class="ms-1 small text-muted">
                                {% if offered == 1 %}
                                    1 project
                                {% else %}
                                    {{ offered }} projects
                                {% endif %}
                                <i class="fas fa-info-circle" tabindex="0" data-bs-toggle="popover" title="Projects offered" data-bs-container="body" data-bs-trigger="focus" data-bs-content="{{ projects_list(projects) }}"></i>
                            </span>
                        {% endif %}
                    </div>
                {% endif %}
            {% endif %}
        </div>
    </div>
{% else %}
    <span class="alert alert-danger p-1"><strong>None</strong></span>
{% endfor %}
"""


# language=jinja2
_full_workload = \
"""
{% set ns = namespace(count=0) %}
{% for record in enrolments %}
    {% if record.pclass_id in wkld %}
        {% set CATS = wkld[record.pclass_id] %}
        {% if CATS > 0 %}
            {% set ns.count = ns.count+1 %}
            <div class="d-flex flex-row justify-content-start align-items-center gap-1">
                {% set swatch_colour = record.pclass.make_CSS_style() %}
                {% if swatch_colour is not none %}
                    <div class="me-1" style="width: 0.8rem; height: 0.8rem; {{ swatch_colour|safe }}"></div>
                {% endif %}
                <span class="small">{{ record.pclass.abbreviation }}</span>
                <span class="text-success small">{{ CATS }} CATS</span>
            </div>
        {% endif %}
    {% endif %}
{% endfor %}
{% if ns.count > 0 %}<hr>{% endif %}
<span class="text-primary mt-2"><strong>{{ tot }} CATS</strong></span>
"""


# language=jinja2
_simple_workload = \
"""
<span class="text-primary"><strong>{{ tot }} CATS</strong></span>
"""


# language=jinja2
_availability = \
"""
{% if u %}
    <span class="text-danger">Unbounded</span>
    <i class="text-muted fas fa-info-circle" data-bs-toggle="tooltip" title="Unbounded availability" data-bs-html="true" title="<em>Unlimited</em> availability means that one or more projects do not have a limit on the number of students"></i>
{% else %}
    <span class="text-success">{{ t|round(2) }}</span>
{% endif %}
"""


# language=jinja2
_full_allocation = \
"""
{%- macro truncate_name(name, maxlength=25) -%}
    {%- if name|length > maxlength -%}
        {{ name[0:maxlength] }}...
    {%- else -%}
        {{ name }}
    {%- endif -%}
{%- endmacro -%}
{# notice need to use single quotes everywhere if the definition of this macro, because it has to go in a data-bs-content attribute #}
{%- macro assigned_list(assigned) -%}
    {%- for record in assigned -%}
        <div class='small'>
            {{ loop.index }}. {{ record.owner.student.user.name }}
            {% if record.project is not none -%}
                <em>{{ truncate_name(record.project.name, maxlength=40) }}</em>
            {%- endif -%}
        </div>
    {%- else -%}
        <span class='small text-danger'><strong>None</strong></span>
    {%- endfor -%}
{%- endmacro -%}
{% macro allocation_list(enrolments, num_dict, CATS_dict, assigned_dict, total, tabindex, title) %}
    {% for record in enrolments %}
        {% if record.pclass_id in num_dict %}
            {% set num = num_dict[record.pclass_id] %}
            {% set CATS = CATS_dict[record.pclass_id] %}
            {% set assigned = assigned_dict[record.pclass_id] %}
            {% if num > 0 %}
                <div class="d-flex flex-row justify-content-start align-items-center gap-2">
                    {% set swatch_colour = record.pclass.make_CSS_style() %}
                    {% if swatch_colour is not none %}
                        <div class="me-1" style="width: 1rem; height: 1rem; {{ swatch_colour|safe }}"></div>
                    {% endif %}
                    <span class="small">{{ record.pclass.abbreviation }}</span>
                    <span class="small text-success"><strong>{{ num }}</strong> &rightarrow; {{ CATS }} CATS</span>
                    <i class="small text-muted fas fa-info-circle" tabindex="{{ tabindex }}" data-bs-toggle="popover" title="{{ title }}" data-bs-container="body" data-bs-trigger="focus" data-bs-content="{{ assigned_list(assigned)|safe }}"></i>
                </div>
            {% endif %}
        {% endif %}
    {% endfor %}
    <div class="mt-1 small text-secondary">
        {{ total }} allocations &rightarrow; {{ CATS_dict.values()|sum }} CATS
    </div>
{% endmacro %}
{% macro presentation_list(enrolments, num_dict, CATS_dict, assigned_dict, total, tabindex, title) %}
    {% for record in enrolments %}
        {% if record.pclass_id in num_dict %}
            {% set num = num_dict[record.pclass_id] %}
            {% set CATS = CATS_dict[record.pclass_id] %}
            {% if num > 0 %}
                <div class="d-flex flex-row justify-content-start align-items-center gap-2">
                    {% set swatch_colour = record.pclass.make_CSS_style() %}
                    {% if swatch_colour is not none %}
                        <div class="me-1" style="width: 1rem; height: 1rem; {{ swatch_colour|safe }}"></div>
                    {% endif %}
                    <span class="small">{{ record.pclass.abbreviation }}</span>
                    <span class="small text-success"><strong>{{ num }}</strong> &rightarrow; {{ CATS }} CATS</span>
                </div>
            {% endif %}
        {% endif %}
    {% endfor %}
    <div class="mt-1 small text-secondary">
        {{ total }} allocations &rightarrow; {{ CATS_dict.values()|sum }} CATS
    </div>
{% endmacro %}
{% if total_supervising > 0 %}
    <div class="bg-light p-2 mb-2">
        <span>Supervising</span>
        {{ allocation_list(enrolments, num_supervising, CATS_supervising, assigned_supervising, total_supervising, "10", "Supervision allocation") }}
    </div>
{% endif %}
{% if total_marking > 0 %}
    <div class="bg-light p-2 mb-2">
        <span>Marking</span>
        {{ allocation_list(enrolments, num_marking, CATS_marking, assigned_marking, total_marking, "11", "Marking allocation") }}
    </div>
{% endif %}
{% if total_moderating > 0 %}
    <div class="bg-light p-2 mb-2">
        <span>Moderating</span>
        {{ allocation_list(enrolments, num_moderating, CATS_moderating, assigned_moderating, total_moderating, "12", "Moderating allocation") }}
    </div>
{% endif %}
{% if total_presentations > 0 %}
    <div class="bg-light p-2 mb-2">
        <span>Presentations</span>
        {{ presentation_list(enrolments, num_presentations, CATS_presentations, assigned_presentations, total_presentations, "13", "Presentations allocation") }}
    </div>
{% endif %}
"""


# language=jinja2
_simple_allocation = \
"""
{% macro allocation_list(CATS_dict, total) %}
    <div class="mt-1 small text-secondary">
        {{ total }} allocations &rightarrow; {{ CATS_dict.values()|sum }} CATS
    </div>
{% endmacro %}
{% if total_supervising > 0 %}
    <div class="bg-light p-2 mb-2">
        <span>Supervising</span>
        {{ allocation_list(CATS_supervising, total_supervising) }}
    </div>
{% endif %}
{% if total_marking > 0 %}
    <div class="bg-light p-2 mb-2">
        <span>Marking</span>
        {{ allocation_list(CATS_marking, total_marking) }}
    </div>
{% endif %}
{% if total_moderating > 0 %}
    <div class="bg-light p-2 mb-2">
        <span>Moderating</span>
        {{ allocation_list(CATS_moderating, total_moderating) }}
    </div>
{% endif %}
{% if total_presentations > 0 %}
    <div class="bg-light p-2 mb-2">
        <span>Presentations</span>
        {{ allocation_list(CATS_presentations, total_presentations) }}
    </div>
{% endif %}
"""


def _element_base(faculty_id, enrolment_template, allocation_template, workload_template):
    f: FacultyData = db.session.query(FacultyData).filter_by(id=faculty_id).one()

    CATS_workload = {}

    CATS_supervising = {}
    CATS_marking = {}
    CATS_moderating = {}
    CATS_presentations = {}

    num_supervising = {}
    num_marking = {}
    num_moderating = {}
    num_presentations = {}

    assigned_supervising = {}
    assigned_marking = {}
    assigned_moderating = {}
    assigned_presentations = {}

    configs = {}

    total_workload = 0

    enrolments = f.ordered_enrollments

    for record in enrolments:
        record: EnrollmentRecord

        supv, mark, mod, pres = f.CATS_assignment(record.pclass)

        pclass_id = record.pclass_id

        CATS_total = supv + mark + mod + pres
        CATS_workload[pclass_id] = CATS_total
        total_workload += CATS_total

        CATS_supervising[pclass_id] = supv
        CATS_marking[pclass_id] = mark
        CATS_moderating[pclass_id] = mod
        CATS_presentations[pclass_id] = pres

        config: ProjectClassConfig = record.pclass.most_recent_config
        configs[pclass_id] = config

        if config.uses_supervisor:
            data = f.supervisor_assignments(config_id=config.id)
            assigned_supervising[pclass_id] = data.all()
            num_supervising[pclass_id] = get_count(data)

        if config.uses_marker:
            data = f.marker_assignments(config_id=config.id)
            assigned_marking[pclass_id] = data.all()
            num_marking[pclass_id] = get_count(data)

        if config.uses_moderator:
            data = f.moderator_assignments(config_id=config.id)
            assigned_moderating[pclass_id] = data.all()
            num_moderating[pclass_id] = get_count(data)

        if config.uses_presentations:
            data = f.presentation_assignments(config_id=config.id)
            assigned_presentations[pclass_id] = data.all()
            num_presentations[pclass_id] = get_count(data)

    total_supervising = sum(num_supervising.values())
    total_marking = sum(num_marking.values())
    total_moderating = sum(num_moderating.values())
    total_presentations = sum(num_presentations.values())

    total_allocation = total_supervising + total_marking + total_moderating + total_presentations

    availability, unbounded = f.student_availability

    # TODO: presentation ScheduleSlot allocation isn't currently attached to the "allocation" entry -
    #  these should be shown, just as for supervising/marking/moderating allocation

    return {'name': {'display': render_template_string(_name, f=f),
                     'sortstring': f.user.last_name + f.user.first_name},
            'groups': render_template_string(_groups, f=f),
            'enrollments': {'display': render_template_string(enrolment_template, f=f, enrolments=enrolments,
                                                              configs=configs),
                            'sortvalue': get_count(f.enrollments)},
            'allocation': {'display': render_template_string(allocation_template, f=f, enrolments=enrolments,
                                                             CATS_supervising=CATS_supervising,
                                                             num_supervising=num_supervising,
                                                             assigned_supervising=assigned_supervising,
                                                             CATS_marking=CATS_marking,
                                                             num_marking=num_marking,
                                                             assigned_marking=assigned_marking,
                                                             CATS_moderating=CATS_moderating,
                                                             num_moderating=num_moderating,
                                                             assigned_moderating=assigned_moderating,
                                                             CATS_presentations=CATS_presentations,
                                                             num_presentations=num_presentations,
                                                             assigned_presentations=assigned_presentations,
                                                             total_supervising=total_supervising,
                                                             total_marking=total_marking,
                                                             total_moderating=total_moderating,
                                                             total_presentations=total_presentations),
                           'sortvalue': total_allocation},
            'availability': {'display': render_template_string(_availability, t=availability, u=unbounded),
                             'sortvalue': 999999 if unbounded else availability},
            'workload': {'display': render_template_string(workload_template, f=f, enrolments=enrolments,
                                                           wkld=CATS_workload, tot=total_workload),
                         'sortvalue': total_workload}}


@cache.memoize()
def _element_full(faculty_id):
    return _element_base(faculty_id, _full_enrollments, _full_allocation, _full_workload)


@cache.memoize()
def _element_simple(faculty_id):
    return _element_base(faculty_id, _simple_enrollments, _simple_allocation, _simple_workload)


def _delete_cache_entry(fac_id):
    cache.delete_memoized(_element_full, fac_id)
    cache.delete_memoized(_element_simple, fac_id)


def _delete_enrolled_cache_entries(target: ProjectClass):
    for fd in target.enrollments:
        fd: FacultyData
        _delete_cache_entry(fd.owner_id)


def _SubmissionRecord_delete_cache(target: SubmissionRecord):
    if not target.retired:

        for role in target.roles:
            role: SubmissionRole
            _delete_cache_entry(role.user_id)


@listens_for(FacultyData.affiliations, 'append')
def _FacultyData_affiliations_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        _delete_cache_entry(target.id)


@listens_for(FacultyData.affiliations, 'remove')
def _FacultyData_affiliations_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        _delete_cache_entry(target.id)


@listens_for(EnrollmentRecord, 'before_insert')
def _EnrollmentRecord_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.owner_id)


@listens_for(EnrollmentRecord, 'before_update')
def _EnrollmentRecord_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.owner_id)


@listens_for(EnrollmentRecord, 'before_delete')
def _EnrollmentRecord_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.owner_id)


@listens_for(SubmissionRecord, 'before_insert')
def _SubmissionRecord_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _SubmissionRecord_delete_cache(target)


@listens_for(SubmissionRecord, 'before_update')
def _SubmissionRecord_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _SubmissionRecord_delete_cache(target)


@listens_for(SubmissionRecord, 'before_delete')
def _SubmissionRecord_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _SubmissionRecord_delete_cache(target)


@listens_for(SubmissionRecord.project, 'set', active_history=True)
def _SubmissionRecord_project_set_receiver(target, value, oldvalue, initiator):
    with db.session.no_autoflush:
        if isinstance(oldvalue, LiveProject):
            _delete_cache_entry(oldvalue.owner_id)

        if isinstance(value, LiveProject):
            _delete_cache_entry(value.owner_id)


@listens_for(SubmissionRole, 'before_insert')
def _SubmissionRole_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.user_id)


@listens_for(SubmissionRole, 'before_update')
def _SubmissionRole_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.user_id)


@listens_for(SubmissionRole, 'before_delete')
def _SubmissionRole_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.user_id)


@listens_for(ProjectClassConfig, 'before_update')
def _ProjectClassConfig_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_enrolled_cache_entries(target.project_class)


@listens_for(ProjectClass, 'before_update')
def _ProjectClass_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_enrolled_cache_entries(target)


# no need for an insert handler for ProjectClassConfig or ProjectClass since at the point of insertion,
# adding new project types cannot change anyone's workload

# no need for a delete handler for ProjectClassConfig or ProjectClass since that will be entailed by the
# removal of the corresponding EnrollmentRecord


def _ScheduleSlot_assessors_delete_cache(target: ScheduleSlot, value):
    if target.owner is not None:
        owner = target.owner
    else:
        owner = db.session.query(ScheduleAttempt).filter_by(id=target.owner_id).first()

    if owner is None:
        return

    if owner.deployed and owner.owner is not None:
        if owner.owner.year == get_current_year():
            _delete_cache_entry(value.id)


@listens_for(ScheduleSlot.assessors, 'append')
def _ScheduleSlot_assessors_append_handler(target: ScheduleSlot, value, initiator):
    with db.session.no_autoflush:
        _ScheduleSlot_assessors_delete_cache(target, value)


@listens_for(ScheduleSlot.assessors, 'remove')
def _ScheduleSlot_assessors_remove_handler(target: ScheduleSlot, value, initiator):
    with db.session.no_autoflush:
        _ScheduleSlot_assessors_delete_cache(target, value)


def workload_data(faculty_ids, simple_display):
    if simple_display:
        data = [_element_simple(f_id) for f_id in faculty_ids]
    else:
        data = [_element_full(f_id) for f_id in faculty_ids]

    return jsonify(data)
