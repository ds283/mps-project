#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_faculty_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button"
            data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            {% if userdata.is_enrolled(pclass) %}
                <a href="{{ url_for('convenor.unenroll', userid=user.id, pclassid=pclass.id) }}">
                    <i class="fa fa-trash"></i> Remove enrollment
                </a>
            {% else %}
                <a href="{{ url_for('convenor.enroll', userid=user.id, pclassid=pclass.id) }}">
                    <i class="fa fa-plus"></i> Enroll
                </a>
            {% endif %}
        </li>
        {% set record = userdata.get_enrollment_record(pclass) %}
        <li {% if record is none %}class="disabled"{% endif %}>
            <a {% if record is not none %}href="{{ url_for('manage_users.edit_enrollment', id=record.id, url=url_for('convenor.faculty', id=pclass.id)) }}"{% endif %}>
                <i class="fa fa-cogs"></i> Edit enrollment...
            </a>
        </li>
        <li {% if record is none %}class="disabled"{% endif %}>
            <a {% if record is not none %}href="{{ url_for('convenor.custom_CATS_limits', record_id=record.id) }}"{% endif %}>
                <i class="fa fa-cogs"></i> Custom CATS limits...
            </a>
        </li>
    </ul>
</div>
"""

_golive = \
"""
{% if config.require_confirm %}
    {% if config.requests_issued %}
        {% if config.is_confirmation_required(userdata) %}
            <span class="label label-warning"><i class="fa fa-times"></i> Outstanding</span>
        {% else %}
            {% if userdata.is_enrolled(pclass) %}
                {% set record = userdata.get_enrollment_record(pclass.id) %}
                {% if record.supervisor_state == record.SUPERVISOR_ENROLLED %}
                    <span class="label label-success"><i class="fa fa-check"></i> Confirmed</span>
                {% elif record.supervisor_state == record.SUPERVISOR_SABBATICAL %}
                    <span class="label label-default"><i class="fa fa-check"></i> Sabbatical</span>
                {% elif record.supervisor_state == record.SUPERVISOR_EXEMPT %}
                    <span class="label label-default"><i class="fa fa-check"></i> Exempt</span>
                {% else %}
                    <span class="label label-danger">Unknown</span>
                {% endif %}
            {% else %}
                <span class="label label-default">Not enrolled</span>
            {% endif %}
        {% endif %}
    {% else %}
        <span class="label label-danger">Not yet issued</span>
    {% endif %}
{% else %}
    <span class="label label-default">Disabled</span>
{% endif %}
"""

_projects = \
"""
{{ d.projects_offered_label(pclass)|safe }}
{{ d.projects_unofferable_label|safe }}
{{ d.marker_label|safe }}
"""

_name = \
"""
<a href="mailto:{{ u.email }}">{{ u.name }}</a>
"""

_enrollments = \
"""
{% set f = d.get_enrollment_record(pclass_id) %}
{% if f is not none %}
    {{ f.enrolled_labels|safe }}
    <div>
        {% if f.CATS_supervision is not none %}
            <span class="label label-warning">S: {{ f.CATS_supervision }} CATS</span>
        {% else %}
            <span class="label label-default">S: Default CATS</span>
        {% endif %}
        {% if f.CATS_marking is not none %}
            <span class="label label-warning">M {{ f.CATS_marking }} CATS</span>
        {% else %}
            <span class="label label-default">M: Default CATS</span>
        {% endif %}
        {% if f.CATS_presentation is not none %}
            <span class="label label-warning">P {{ f.CATS_marking }} CATS</span>
        {% else %}
            <span class="label label-default">P: Default CATS</span>
        {% endif %}
    </div>
{% else %}
    <span class="label label-default">Not enrolled</span>
{% endif %}
"""


def faculty_data(faculty, pclass, config):

    data = [{'name': {'display': render_template_string(_name, u=u, d=d, pclass_id=pclass.id),
                      'sortstring': u.last_name + u.first_name},
             'email': '<a href="mailto:{em}">{em}</a>'.format(em=u.email),
             'user': u.username,
             'enrolled': render_template_string(_enrollments, d=d, pclass_id=pclass.id),
             'projects': render_template_string(_projects, d=d, pclass=pclass),
             'golive': render_template_string(_golive, config=config, pclass=pclass, user=u, userdata=d),
             'menu': render_template_string(_faculty_menu, pclass=pclass, user=u, userdata=d)} for u, d in faculty]

    return jsonify(data)
