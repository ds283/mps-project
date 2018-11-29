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


_date = \
"""
{{ s.date_as_string }}
{% if not s.is_valid %}
    <i class="fa fa-exclamation-triangle" style="color:red;"></i>
    <p></p>
    {% set errors = s.errors %}
    {% set warnings = s.warnings %}
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
                {% if loop.index <= 5 %}
                    <p class="help-block">{{ item }}</p>
                {% elif loop.index == 6 %}
                    <p class="help-block">...</p>
                {% endif %}            
            {% endfor %}
        </div>
    {% endif %}
    {% if warnings|length > 0 %}
        <div class="has-error">
            {% for item in warnings %}
                {% if loop.index <= 5 %}
                    <p class="help-block">Warning: {{ item }}</p>
                {% elif loop.index == 6 %}
                    <p class="help-block">...</p>
                {% endif %}
            {% endfor %}
        </div>
    {% endif %}
{% endif %}
"""


_rooms = \
"""
{% for room in s.ordered_rooms %}
    {{ room.label|safe }}
{% else %}
    <span class="label label-warning"><i class="fa fa-times"></i> No rooms attached</span>
{% endfor %}
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        {% set a = s.owner %}
        {% set disabled = not s.owner.feedback_open %}
        <li class="dropdown-header">Edit session</li>
        <li {% if disabled %}class="disabled"{% endif %}>
            <a {% if not disabled %}href="{{ url_for('admin.edit_session', id=s.id) }}"{% endif %}>
                <i class="fa fa-cogs"></i> Settings...
            </a>
        </li>
        {% set disabled = not a.requested_availability or a.is_deployed %}
        <li {% if disabled %}class="disabled"{% endif %}>
            <a {% if not disabled %}href="{{ url_for('admin.submitter_session_availability', id=s.id) }}"{% endif %}>
                <i class="fa fa-cogs"></i> Submitters...
            </a>
        </li>
        <li {% if disabled %}class="disabled"{% endif %}>
            <a {% if not disabled %}href="{{ url_for('admin.assessor_session_availability', id=s.id) }}"{% endif %}>
                <i class="fa fa-cogs"></i> Assessors...
            </a>
        </li>
        {% set disabled = not a.feedback_open %}
        <li {% if disabled %}class="disabled"{% endif %}>
            <a {% if not disabled %}href="{{ url_for('admin.delete_session', id=s.id) }}"{% endif %}>
                <i class="fa fa-trash"></i> Delete
            </a>
        </li>
    </ul>
</div>
"""


_faculty = \
"""
{% if s.owner.availability_lifecycle > s.owner.AVAILABILITY_NOT_REQUESTED %}
    {% set available = s.number_available_faculty %}
    {% set ifneeded = s.number_ifneeded_faculty %}
    {% if available > 0 or ifneeded > 0 %}
        <span class="label label-primary">{{ available }}{% if ifneeded > 0 %}(+{{ ifneeded }}){% endif %} available</span>
    {% else %}
        <span class="label label-danger">No availability</span>
    {% endif %}
{% else %}
    <span class="label label-default">Not yet requested</span>
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
