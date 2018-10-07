#
# Created by David Seery on 2018-09-28.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_name = \
"""
<a href="{{ url_for('admin.assessment_manage_sessions', id=a.id) }}">{{ a.name }}</a>
{% if not a.is_valid %}
    <i class="fa fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
"""


_periods = \
"""
{% for period in a.submission_periods %}
    {{ period.label|safe }}
{% endfor %}
"""


_sessions = \
"""
{% set sessions = a.ordered_sessions.all() %}
{% for session in sessions %}
    {% if a.requested_availability %}
        {{ session.make_label(session.short_date_as_string + ' ' + session.session_type_string + ' (' + session.faculty_count|string + ')')|safe }}
    {% else %}
        {{ session.label|safe }}
    {% endif %}
{% endfor %}
{% if sessions|length > 0 %}
    <p></p>
    {% set errors = a.errors %}
    {% set warnings = a.warnings %}
    {% if errors|length == 1 %}
        <span class="label label-danger">1 error</span>
    {% elif errors|length > 1 %}
        <span class="label label-danger">{{ errors|length }} errors</span>
    {% else %}
        <span class="label label-success">0 errors</span>
    {% endif %}
    {% if warnings|length == 1 %}
        <span class="label label-warning">1 warning</span>
    {% elif warnings|length > 1 %}
        <span class="label label-warning">{{ warnings|length }} warnings</span>
    {% else %}
        <span class="label label-success">0 warnings</span>
    {% endif %}
    {% if errors|length > 0 %}
        <div class="has-error">
            {% for item in errors %}
                {% if loop.index <= 10 %}
                    <p class="help-block">{{ item }}</p>
                {% elif loop.index == 11 %}
                    <p class="help-block">...</p>
                {% endif %}            
            {% endfor %}
        </div>
    {% endif %}
    {% if warnings|length > 0 %}
        <div class="has-error">
            {% for item in warnings %}
                {% if loop.index <= 10 %}
                    <p class="help-block">{{ item }}</p>
                {% elif loop.index == 11 %}
                    <p class="help-block">...</p>
                {% endif %}
            {% endfor %}
        </div>
    {% endif %}
{% endif %}
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li class="dropdown-header">Operations</li>
        <li>
            <a href="{{ url_for('admin.assessment_availability', id=a.id) }}">
                <i class="fa fa-calendar"></i> Faculty availability...
            </a>
        </li>
        {% set disabled = not a.availability_closed %}
        <li {% if disabled %}class="disabled"{% endif %}>
            <a {% if not disabled %}href="{{ url_for('admin.assessment_schedules', id=a.id) }}"{% endif %}>
                <i class="fa fa-wrench"></i> Schedule...
            </a>
        </li>
        
        <li role="separator" class="divider">
        <li class="dropdown-header">Edit assessment</li>
        {% set disabled = a.requested_availability %}
        <li {% if disabled %}class="disabled"{% endif %}>
            <a {% if not disabled %}href="{{ url_for('admin.edit_assessment', id=a.id) }}"{% endif %}>
                <i class="fa fa-cogs"></i> Settings
            </a>
        </li>
        <li>
            <a href="{{ url_for('admin.assessment_manage_sessions', id=a.id) }}">
                <i class="fa fa-calendar"></i> Sessions...
            </a>
        </li>
        <li>
            <a href="{{ url_for('admin.delete_assessment', id=a.id) }}">
                <i class="fa fa-trash"></i> Delete
            </a>
        </li>
    </ul>
</div>
"""


def presentation_assessments_data(assessments):

    data=[{'name': render_template_string(_name, a=a),
           'periods': render_template_string(_periods, a=a),
           'sessions': render_template_string(_sessions, a=a),
           'menu': render_template_string(_menu, a=a)} for a in assessments]

    return jsonify(data)
