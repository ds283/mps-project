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


# language=jinja2
_faculty_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button"
            data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        {% if userdata.is_enrolled(pclass) %}
            <a class="dropdown-item" href="{{ url_for('convenor.unenroll', userid=user.id, pclassid=pclass.id) }}">
                <i class="fas fa-trash fa-fw"></i> Remove enrollment
            </a>
        {% else %}
            <a class="dropdown-item" href="{{ url_for('convenor.enroll', userid=user.id, pclassid=pclass.id) }}">
                <i class="fas fa-plus fa-fw"></i> Enroll
            </a>
        {% endif %}
        {% set record = userdata.get_enrollment_record(pclass) %}
        <a class="dropdown-item {% if record is none %}disabled{% endif %}" {% if record is not none %}href="{{ url_for('manage_users.edit_enrollment', id=record.id, url=url_for('convenor.faculty', id=pclass.id)) }}"{% endif %}>
            <i class="fas fa-cogs fa-fw"></i> Edit enrollment...
        </a>
        <a class="dropdown-item {% if record is none %}disabled{% endif %}" {% if record is not none %}href="{{ url_for('convenor.custom_CATS_limits', record_id=record.id) }}"{% endif %}>
            <i class="fas fa-cogs fa-fw"></i> Custom CATS limits...
        </a>
    </div>
</div>
"""

# language=jinja2
_golive = \
"""
{% if config.require_confirm %}
    {% if config.requests_issued %}
        {% if config.is_confirmation_required(userdata) %}
            <span class="badge badge-warning"><i class="fas fa-times"></i> Outstanding</span>
        {% else %}
            {% if userdata.is_enrolled(pclass) %}
                {% set record = userdata.get_enrollment_record(pclass.id) %}
                {% if record.supervisor_state == record.SUPERVISOR_ENROLLED %}
                    <span class="badge badge-success"><i class="fas fa-check"></i> Confirmed</span>
                {% elif record.supervisor_state == record.SUPERVISOR_SABBATICAL %}
                    <span class="badge badge-secondary"><i class="fas fa-check"></i> Sabbatical</span>
                {% elif record.supervisor_state == record.SUPERVISOR_EXEMPT %}
                    <span class="badge badge-secondary"><i class="fas fa-check"></i> Exempt</span>
                {% else %}
                    <span class="badge badge-danger">Unknown</span>
                {% endif %}
            {% else %}
                <span class="badge badge-secondary">Not enrolled</span>
            {% endif %}
        {% endif %}
    {% else %}
        <span class="badge badge-danger">Not yet issued</span>
    {% endif %}
{% else %}
    <span class="badge badge-secondary">Disabled</span>
{% endif %}
"""

# language=jinja2
_projects = \
"""
{{ d.projects_offered_label(pclass)|safe }}
{{ d.projects_unofferable_label|safe }}
{{ d.marker_label|safe }}
"""

# language=jinja2
_name = \
"""
<a href="mailto:{{ u.email }}">{{ u.name }}</a>
"""

# language=jinja2
_enrollments = \
"""
{% set f = d.get_enrollment_record(pclass_id) %}
{% if f is not none %}
    {{ f.enrolled_labels|safe }}
    <div>
        {% if f.CATS_supervision is not none %}
            <span class="badge badge-warning">S: {{ f.CATS_supervision }} CATS</span>
        {% else %}
            <span class="badge badge-secondary">S: Default CATS</span>
        {% endif %}
        {% if f.CATS_marking is not none %}
            <span class="badge badge-warning">M {{ f.CATS_marking }} CATS</span>
        {% else %}
            <span class="badge badge-secondary">M: Default CATS</span>
        {% endif %}
        {% if f.CATS_presentation is not none %}
            <span class="badge badge-warning">P {{ f.CATS_marking }} CATS</span>
        {% else %}
            <span class="badge badge-secondary">P: Default CATS</span>
        {% endif %}
    </div>
{% else %}
    <span class="badge badge-secondary">Not enrolled</span>
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
