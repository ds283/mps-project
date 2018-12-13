#
# Created by David Seery on 2018-10-22.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for


_session_actions = \
"""
{% set available = s.faculty_available(f.id) %}
{% set ifneeded = s.faculty_ifneeded(f.id) %}
<div style="text-align: right;">
    <div class="pull-right">
        {% if available %}
            <a class="btn btn-sm btn-success">
                <i class="fa fa-check"></i> Available
            </a>
            <a class="btn btn-sm btn-default" href="{{ url_for('admin.session_ifneeded', f_id=f.id, s_id=s.id) }}">
                If needed
            </a>
            <a class="btn btn-sm btn-default" href="{{ url_for('admin.session_unavailable', f_id=f.id, s_id=s.id) }}">
                <i class="fa fa-times"></i> Not available
            </a>
        {% elif ifneeded %}
            <a class="btn btn-sm btn-default" href="{{ url_for('admin.session_available', f_id=f.id, s_id=s.id) }}">
                <i class="fa fa-check"></i> Available
            </a>
            <a class="btn btn-sm btn-warning">
                If needed
            </a>
            <a class="btn btn-sm btn-default" href="{{ url_for('admin.session_unavailable', f_id=f.id, s_id=s.id) }}">
                <i class="fa fa-times"></i> Not available
            </a>
        {% else %}
            <a class="btn btn-sm btn-default" href="{{ url_for('admin.session_available', f_id=f.id, s_id=s.id) }}">
                <i class="fa fa-check"></i> Available
            </a>
            <a class="btn btn-sm btn-default" href="{{ url_for('admin.session_ifneeded', f_id=f.id, s_id=s.id) }}">
                If needed
            </a>
            <a class="btn btn-sm btn-danger">
                <i class="fa fa-times"></i> Not available
            </a>
        {% endif %}
    </div>
</div>
"""


_confirmed = \
"""
{% if rec.confirmed %}
    <span class="label label-primary">Yes</span>
    {% if rec.confirmed_timestamp is not none %}
        <span class="label label-info">{{ rec.confirmed_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}</span>
    {% endif %}
{% else %}
    <span class="label label-warning">No</span>
{% endif %}
"""


_assessor_actions = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('admin.assessment_assessor_availability', a_id=a.id, f_id=f.id, text='assessment assessor list', url=url_for('admin.assessment_manage_assessors', id=a.id)) }}">
                <i class="fa fa-calendar"></i> Sessions...
            </a>
        </li>
        {% set disabled = not a.is_faculty_outstanding(f.id) %} 
        <li {% if disabled %}class="disabled"{% endif %}>
            <a {% if not disabled %}href="{{ url_for('admin.force_confirm_availability', assessment_id=a.id, faculty_id=f.id) }}"{% endif %}>
                <i class="fa fa-check"></i> {% if not disabled %}Force confirm{% else %}Confirmed{% endif %}
            </a>
        </li>
        <li>
            <a href="{{ url_for('admin.schedule_set_limit', assessment_id=a.id, faculty_id=f.id, text='assessment assessor list', url=url_for('admin.assessment_manage_assessors', id=a.id)) }}">
                <i class="fa fa-cogs"></i> Set assignment limit...
            </a>
        </li>
        <li>
            <a href="{{ url_for('admin.remove_assessor', assessment_id=a.id, faculty_id=f.id) }}">
                <i class="fa fa-trash"></i> Remove
            </a>
        </li>
    </ul>
</div>
"""


_comment = \
"""
{% if rec.comment is not none and rec.comment|length > 0 %}
    {{ rec.comment }}
{% else %}
    <span class="label label-default">None</span>
{% endif %}
"""


_availability = \
"""
<span class="label label-success">{{ rec.number_available }}</span>
<span class="label label-warning">{{ rec.number_ifneeded }}</span>
<span class="label label-danger">{{ rec.number_unavailable }}</span>
"""


_name = \
"""
<a href="mailto:{{ rec.faculty.user.email }}">{{ rec.faculty.user.name }}</a>
{% if rec.assigned_limit is not none %}
    <div>
        <span class="label label-primary">Assignment limit {{ rec.assigned_limit }}</span>
    </div>
{% endif %}
"""



def assessor_session_availability_data(assessment, session, assessors):
    data = [{'name': {'display': render_template_string(_name, rec=assessor),
                      'sortstring': assessor.faculty.user.last_name + assessor.faculty.user.first_name},
             'confirmed': render_template_string(_confirmed, a=assessment, rec=assessor),
             'comment': render_template_string(_comment, rec=assessor),
             'availability': {'display': render_template_string(_availability, rec=assessor),
                              'sortvalue': assessor.number_available},
             'menu': render_template_string(_session_actions, s=session, f=assessor.faculty)} for assessor in assessors]

    return jsonify(data)


def presentation_assessors_data(assessment, assessors):
    data = [{'name': {'display': render_template_string(_name, rec=assessor),
                      'sortstring': assessor.faculty.user.last_name + assessor.faculty.user.first_name},
             'confirmed': render_template_string(_confirmed, a=assessment, rec=assessor),
             'comment': render_template_string(_comment, rec=assessor),
             'availability': {'display': render_template_string(_availability, rec=assessor),
                              'sortvalue': assessor.number_available},
             'menu': render_template_string(_assessor_actions, a=assessment, f=assessor.faculty)} for assessor in assessors]

    return jsonify(data)
