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
            <a {% if record is not none %}href="{{ url_for('admin.edit_enrollment', id=record.id, url=url_for('convenor.faculty', id=pclass.id)) }}"{% endif %}>
                <i class="fa fa-cogs"></i> Edit enrollment
            </a>
        </li>
    </ul>
</div>
"""

_golive = \
"""
{% if config.require_confirm %}
    {% if config.requests_issued %}
        {% if userdata in config.golive_required %}
            <span class="label label-warning"><i class="fa fa-times"></i> Outstanding</span>
        {% else %}
            {% if userdata.is_enrolled(pclass) %}
                <span class="label label-success"><i class="fa fa-check"></i> Confirmed</span>
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


def faculty_data(faculty, pclass, config):

    data = [{'name': {'display': '<a href="mailto:{email}">{name}</a>'.format(email=u.email, name=u.name),
                      'sortstring': u.last_name + u.first_name},
             'email': '<a href="mailto:{em}">{em}</a>'.format(em=u.email),
             'user': u.username,
             'enrolled': d.enrolled_labels(pclass),
             'projects': render_template_string(_projects, d=d, pclass=pclass),
             'golive': render_template_string(_golive, config=config, pclass=pclass, user=u, userdata=d),
             'menu': render_template_string(_faculty_menu, pclass=pclass, user=u, userdata=d)} for u, d in faculty]

    return jsonify(data)
