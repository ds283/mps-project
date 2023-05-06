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
    SubmissionRole, ProjectClassConfig
from ...shared.sqlalchemy import get_count
from ...shared.utils import get_current_year


# language=jinja2
_name = \
"""
<a class="text-decoration-none" href="mailto:{{ f.user.email }}">{{ f.user.name }}</a>
{% if overassigned %}
    <i class="fas fa-exclamation-triangle" style="color:red;"></i>
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
{% for record in f.ordered_enrollments %}
    <div {% if loop.index > 1 %}style="top-padding: 8px;"{% endif %}>
        {{ record.pclass.make_label()|safe }}

        {% if record.pclass.uses_supervisor %}
            {% set offered = f.number_projects_offered(record.pclass) %}
            {% if offered > 0 %}
                {% set projects = f.projects_offered(record.pclass) %}
                <span class="badge bg-info text-dark" data-bs-toggle="tooltip" data-html="true" title="{% for p in projects %}<p>{{ loop.index }}. {{ p.name }}</p>{% endfor %}">Offered={{ offered }}</span>
            {% else %}
                <span class="badge bg-danger">Offered=0</span>
            {% endif %}
            {{ record.short_supervisor_label|safe }}
        {% endif %}

        {% if record.pclass.uses_marker %}
            {{ record.short_marker_label|safe }}
        {% endif %}

        {% if record.pclass.uses_presentations %}
            {{ record.short_presentation_label|safe }}
        {% endif %}
    </div>
{% else %}
    <span class="badge bg-secondary">None</span>
{% endfor %}
"""


# language=jinja2
_simple_enrollments = \
"""
{% for record in f.ordered_enrollments %}
    <div {% if loop.index > 1 %}style="top-padding: 8px;"{% endif %}>
        {{ record.pclass.make_label()|safe }}

        {% if record.pclass.uses_supervisor %}
            {% set offered = f.number_projects_offered(record.pclass) %}
            {% if offered > 0 %}
                <span class="badge bg-info text-dark" data-bs-toggle="tooltip" data-html="true" title="{% for p in projects %}<p>{{ loop.index }}. {{ p.name }}</p>{% endfor %}">Offered={{ offered }}</span>
            {% else %}
                <span class="badge bg-danger">Offered=0</span>
            {% endif %}
        {% endif %}
    </div>
{% else %}
    <span class="badge bg-secondary">None</span>
{% endfor %}
"""


# language=jinja2
_full_workload = \
"""
{% for record in f.ordered_enrollments %}
    {{ record.pclass.make_label(record.pclass.abbreviation + ' ' + wkld[record.pclass_id]|string)|safe }}
{% else %}
    <span class="badge bg-secondary">None</span>
{% endfor %}
<p></p>
<span class="badge bg-primary">Total {{ tot }}</span>
"""


# language=jinja2
_simple_workload = \
"""
<span class="badge bg-primary">{{ tot }}</span>
"""


# language=jinja2
_availability = \
"""
{% if u %}
    <span class="badge bg-info text-dark" data-bs-toggle="tooltip" title="One or more projects do not have a limit on the number of students">Unbounded</span>
{% else %}
    <span data-bs-toggle="tooltip" data-html="true" title="<i>Availability</i> is the maximum CATS-weighted number of students who could be assigned to this supervisor">{{ t|round(2) }}</span>
{% endif %}
"""


# language=jinja2
_full_assignments = \
"""
{% for record in f.ordered_enrollments %}
    {{ record.pclass.make_label(record.pclass.abbreviation + ' ' + data[record.pclass_id]|string)|safe }}
{% else %}
    <span class="badge bg-secondary">None</span>
{% endfor %}
<p></p>
<span class="badge bg-primary">Total {{ total }}</span>
"""


# language=jinja2
_simple_assignments = \
"""
<span class="badge bg-primary">Total {{ total }}</span>
"""


def _element_base(faculty_id, enrollment_template, assignments_template, workload_template):
    f: FacultyData = db.session.query(FacultyData).filter_by(id=faculty_id).one()

    workload = {}
    supervising = {}
    marking = {}
    presentations = {}

    total_workload = 0

    for record in f.enrollments:
        record: EnrollmentRecord

        CATS = sum(f.CATS_assignment(record.pclass))
        workload[record.pclass_id] = CATS

        config: ProjectClassConfig = record.pclass.most_recent_config

        if config.uses_supervisor:
            supervising[record.pclass_id] = get_count(f.supervisor_assignments(config_id=config.id))

        if config.uses_marker:
            marking[record.pclass_id] = get_count(f.marker_assignments(config_id=config.id))

        if config.uses_presentations:
            presentations[record.pclass_id] = get_count(f.presentation_assignments(config_id=config.id))

        total_workload += CATS

    total_supervising = sum(supervising.values())
    total_marking = sum(marking.values())
    total_presentations = sum(presentations.values())

    total, unbounded = f.student_availability

    return {'name': {'display': render_template_string(_name, f=f),
                     'sortstring': f.user.last_name + f.user.first_name},
            'groups': render_template_string(_groups, f=f),
            'enrollments': {'display': render_template_string(enrollment_template, f=f),
                            'sortvalue': get_count(f.enrollments)},
            'supervising': {'display': render_template_string(assignments_template, f=f, data=supervising, total=total_supervising),
                            'sortvalue': total_supervising},
            'marking': {'display': render_template_string(assignments_template, f=f, data=marking, total=total_marking),
                        'sortvalue': total_marking},
            'presentations': {'display': render_template_string(assignments_template, f=f, data=presentations, total=total_presentations),
                              'sortvalue': total_presentations},
            'availability': {'display': render_template_string(_availability, t=total, u=unbounded),
                             'sortvalue': 999999 if unbounded else total},
            'workload': {'display': render_template_string(workload_template, f=f, wkld=workload, tot=total_workload),
                         'sortvalue': total_workload}}


@cache.memoize()
def _element_full(faculty_id):
    return _element_base(faculty_id, _full_enrollments, _full_assignments, _full_workload)


@cache.memoize()
def _element_simple(faculty_id):
    return _element_base(faculty_id, _simple_enrollments, _simple_assignments, _simple_workload)


def _delete_cache_entry(fac_id):
    cache.delete_memoized(_element_full, fac_id)
    cache.delete_memoized(_element_simple, fac_id)


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


def _SubmissionRecord_delete_cache(target):
    if not target.retired:

        for role in target.roles:
            role: SubmissionRole
            _delete_cache_entry(role.user_id)


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


@listens_for(SubmissionRecord.marker, 'set', active_history=True)
def _SubmissionRecord_project_set_receiver(target, value, oldvalue, initiator):
    with db.session.no_autoflush:
        if isinstance(oldvalue, FacultyData):
            _delete_cache_entry(oldvalue.id)

        if isinstance(value, FacultyData):
            _delete_cache_entry(value.id)


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
