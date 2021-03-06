#
# Created by David Seery on 2018-09-30.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify

import calendar


# language=jinja2
_date = \
"""
{{ s.date_as_string }}
{% if s.has_issues %}
    <i class="fas fa-exclamation-triangle" style="color:red;"></i>
    <p></p>
    {% set errors = s.errors %}
    {% set warnings = s.warnings %}
    {% if errors|length == 1 %}
        <span class="badge badge-danger">1 error</span>
    {% elif errors|length > 1 %}
        <span class="badge badge-danger">{{ errors|length }} errors</span>
    {% else %}
        <span class="badge badge-success">0 errors</span>
    {% endif %}
    {% if warnings|length == 1 %}
        <span class="badge badge-warning">1 warning</span>
    {% elif warnings|length > 1 %}
        <span class="badge badge-warning">{{ warnings|length }} warnings</span>
    {% else %}
        <span class="badge badge-success">0 warnings</span>
    {% endif %}
    {% if errors|length > 0 %}
        <div class="error-block">
            {% for item in errors %}
                {% if loop.index <= 5 %}
                    <div class="error-message">{{ item }}</div>
                {% elif loop.index == 6 %}
                    <div class="error-message">Further errors suppressed...</div>
                {% endif %}            
            {% endfor %}
        </div>
    {% endif %}
    {% if warnings|length > 0 %}
        <div class="error-block">
            {% for item in warnings %}
                {% if loop.index <= 5 %}
                    <div class="error-message">Warning: {{ item }}</div>
                {% elif loop.index == 6 %}
                    <div class="error-message">Further errors suppressed...</div>
                {% endif %}
            {% endfor %}
        </div>
    {% endif %}
{% endif %}
"""


# language=jinja2
_rooms = \
"""
{% for room in s.ordered_rooms %}
    {{ room.label|safe }}
{% else %}
    <span class="badge badge-warning"><i class="fas fa-times"></i> No rooms attached</span>
{% endfor %}
"""


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        {% set a = s.owner %}
        {% set disabled = not s.owner.is_feedback_open %}
        <div class="dropdown-header">Edit session</div>
        <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.edit_session', id=s.id) }}"{% endif %}>
            <i class="fas fa-sliders-h fa-fw"></i> Settings...
        </a>
        {% set disabled = not a.requested_availability or a.is_deployed %}
        <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.submitter_session_availability', id=s.id) }}"{% endif %}>
            <i class="fas fa-cogs fa-fw"></i> Submitters...
        </a>
        <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.assessor_session_availability', id=s.id) }}"{% endif %}>
            <i class="fas fa-cogs fa-fw"></i> Assessors...
        </a>
        {% set disabled = not a.is_feedback_open %}
        <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.delete_session', id=s.id) }}"{% endif %}>
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    </div>
</div>
"""


# language=jinja2
_faculty = \
"""
{% if s.owner.availability_lifecycle > s.owner.AVAILABILITY_NOT_REQUESTED %}
    {% set fac_available = s.number_available_faculty %}
    {% set fac_ifneeded = s.number_ifneeded_faculty %}
    {% set fac_unavailable = s.number_unavailable_faculty %}
    {% if fac_available > 0 or fac_ifneeded > 0 %}
        <div>
            <span class="badge badge-primary">{{ fac_available }} available</span>
            {% if fac_ifneeded > 0 %}
                <span class="badge badge-warning">{{ fac_ifneeded }} if needed</span>
            {% endif %}
            {% if fac_unavailable > 0 %}
                <span class="badge badge-danger">{{ fac_unavailable }} unavailable</span>
            {% endif %}
            <span class="badge badge-info">Total {{ fac_available + fac_ifneeded }}</span>
        </div>
    {% else %}
        <span class="badge badge-danger">No availability</span>
    {% endif %}
    {% set sub_unavailable = s.number_unavailable_submitters %}
    {% if sub_unavailable > 0 %}
        {% set pl = 's' %}
        {% if sub_unavailable == 1 %}{% set pl = '' %}{% endif %}
        <span class="badge badge-danger">{{ sub_unavailable }} submitter{{ pl }} unavailable</span>
    {% else %}
        <span class="badge badge-primary">All submitters available</span>
    {% endif %}
{% else %}
    <span class="badge badge-secondary">Not yet requested</span>
{% endif %}
"""


def assessment_sessions_data(sessions):

    data = [{'date': {'display': render_template_string(_date, s=s),
                      'timestamp': calendar.timegm(s.date.timetuple())},
             'session': s.session_type_label,
             'rooms': render_template_string(_rooms, s=s),
             'availability': render_template_string(_faculty, s=s),
             'menu': render_template_string(_menu, s=s)} for s in sessions]

    return jsonify(data)
