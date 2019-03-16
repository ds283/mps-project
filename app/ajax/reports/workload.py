#
# Created by David Seery on 2018-11-01.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for

from ...database import db
from ...models import FacultyData, EnrollmentRecord, SubmissionRecord, ScheduleSlot, LiveProject
from ...cache import cache
from ...shared.sqlalchemy import get_count
from ...shared.utils import get_current_year

from sqlalchemy.event import listens_for



_name = \
"""
<a href="mailto:{{ f.user.email }}">{{ f.user.name }}</a>
{% if overassigned %}
    <i class="fa fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
"""


_groups = \
"""
{% for g in f.affiliations %}
    {{ g.make_label()|safe }}
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
"""


_full_enrollments = \
"""
{% for record in f.ordered_enrollments %}
    <div {% if loop.index > 1 %}style="top-padding: 8px;"{% endif %}>
        {{ record.pclass.make_label()|safe }}

        {% if record.pclass.uses_supervisor %}
            {% set offered = f.number_projects_offered(record.pclass) %}
            {% if offered > 0 %}
                <span class="label label-info">Offered={{ offered }}</span>
            {% else %}
                <span class="label label-danger">Offered=0</span>
            {% endif %}
            {% if record.supervisor_state == record.SUPERVISOR_ENROLLED %}
                <span class="label label-success"><i class="fa fa-check"></i> Supv: active</span>
            {% elif record.supervisor_state == record.SUPERVISOR_SABBATICAL %}
                <span class="label label-warning"><i class="fa fa-times"></i> Supv: sabbat</span>
            {% elif record.supervisor_state == record.SUPERVISOR_EXEMPT %}
                <span class="label label-danger"><i class="fa fa-times"></i> Supv: exempt</span>
            {% else %}
                <span class="label label-danger"><i class="fa fa-times"></i> Supv: unknown</span>
            {% endif %}
        {% endif %}

        {% if record.pclass.uses_marker %}
            {% if record.marker_state == record.MARKER_ENROLLED %}
                <span class="label label-success"><i class="fa fa-check"></i> Mark: active</span>
            {% elif record.marker_state == record.MARKER_SABBATICAL %}
                <span class="label label-warning"><i class="fa fa-times"></i> Mark: sabbat</span>
            {% elif record.marker_state == record.MARKER_EXEMPT %}
                <span class="label label-danger"><i class="fa fa-times"></i> Mark: exempt</span>
            {% else %}
                <span class="label label-danger"><i class="fa fa-times"></i> Mark: unknown</span>
            {% endif %}
        {% endif %}

        {% if record.pclass.uses_presentations %}
            {% if record.presentations_state == record.PRESENTATIONS_ENROLLED %}
                <span class="label label-success"><i class="fa fa-check"></i> Pres: active</span>
            {% elif record.presentations_state == record.PRESENTATIONS_SABBATICAL %}
                <span class="label label-warning"><i class="fa fa-times"></i> Pres: sabbat</span>
            {% elif record.presentations_state == record.PRESENTATIONS_EXEMPT %}
                <span class="label label-danger"><i class="fa fa-times"></i> Pres: exempt</span>
            {% else %}
                <span class="label label-danger"><i class="fa fa-times"></i> Pres: unknown</span>
            {% endif %}
        {% endif %}
    </div>
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
"""


_simple_enrollments = \
"""
{% for record in f.ordered_enrollments %}
    <div {% if loop.index > 1 %}style="top-padding: 8px;"{% endif %}>
        {{ record.pclass.make_label()|safe }}

        {% if record.pclass.uses_supervisor %}
            {% set offered = f.number_projects_offered(record.pclass) %}
            {% if offered > 0 %}
                <span class="label label-info">Offered={{ offered }}</span>
            {% else %}
                <span class="label label-danger">Offered=0</span>
            {% endif %}
        {% endif %}
    </div>
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
"""


_full_workload = \
"""
{% for record in f.ordered_enrollments %}
    {{ record.pclass.make_label(record.pclass.abbreviation + ' ' + wkld[record.pclass_id]|string)|safe }}
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
<p></p>
<span class="label label-primary">Total = {{ tot }}</span>
"""


_simple_workload = \
"""
<span class="label label-primary">{{ tot }}</span>
"""


def _element_base(faculty_id, enrollment_template, workload_template):
    f = db.session.query(FacultyData).filter_by(id=faculty_id).one()

    workload = {}
    total_workload = 0

    for record in f.enrollments:
        CATS = sum(f.CATS_assignment(record.pclass))
        workload[record.pclass_id] = CATS
        total_workload += CATS

    return {'name': {'display': render_template_string(_name, f=f),
                              'sortstring': f.user.last_name + f.user.first_name},
                     'groups': render_template_string(_groups, f=f),
                     'enrollments': {'display': render_template_string(enrollment_template, f=f),
                                     'sortvalue': get_count(f.enrollments)},
                     'workload': {'display': render_template_string(workload_template, f=f, wkld=workload, tot=total_workload),
                                  'sortvalue': total_workload}}


@cache.memoize()
def _element_full(faculty_id):
    return _element_base(faculty_id, _full_enrollments, _full_workload)


@cache.memoize()
def _element_simple(faculty_id):
    return _element_base(faculty_id, _simple_enrollments, _simple_workload)


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
def _EnrollemntRecord_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.owner_id)


@listens_for(EnrollmentRecord, 'before_update')
def _EnrollemntRecord_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.owner_id)


@listens_for(EnrollmentRecord, 'before_delete')
def _EnrollemntRecord_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_cache_entry(target.owner_id)


def _SubmissionRecord_delete_cache(target):
    if not target.retired:

        if target.project is not None:
            _delete_cache_entry(target.project.owner_id)

        elif target.project_id is not None:
            proj = db.session.query(LiveProject).filter_by(id=target.project_id).first()
            if proj is not None:
                _delete_cache_entry(proj.owner_id)

        _delete_cache_entry(target.marker_id)


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


def _ScheduleSlot_assessors_delete_cache(target, value):
    if target.owner.deployed:
        current_year = get_current_year()
        if target.owner.owner.year == current_year:
            _delete_cache_entry(value.id)


@listens_for(ScheduleSlot.assessors, 'append')
def _ScheduleSlot_assessors_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        _ScheduleSlot_assessors_delete_cache(target, value)


@listens_for(ScheduleSlot.assessors, 'remove')
def _ScheduleSlot_assessors_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        _ScheduleSlot_assessors_delete_cache(target, value)


def workload_data(faculty_ids, simple_display):
    if simple_display:
        data = [_element_simple(f_id) for f_id in faculty_ids]
    else:
        data = [_element_full(f_id) for f_id in faculty_ids]

    return jsonify(data)