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


_date = \
"""
{{ s.date_as_string }}
{% if not s.is_valid %}
    <i class="fa fa-exclamation-triangle" style="color:red;"></i>
    <div class="has-error">
        <p class="help-block">Error: {{ s.error }}</p>
    </div>
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
        {% set disabled = not s.owner.feedback_open %}
        <li class="dropdown-header">Edit session</li>
        <li {% if disabled %}class="disabled"{% endif %}>
            <a {% if not disabled %}href="{{ url_for('admin.edit_session', id=s.id) }}"{% endif %}>
                <i class="fa fa-cogs"></i> Settings
            </a>
        </li>
        <li {% if disabled %}class="disabled"{% endif %}>
            <a {% if not disabled %}href="{{ url_for('admin.edit_availabilities', id=s.id) }}"{% endif %}>
                <i class="fa fa-cogs"></i> Edit availabilities...
            </a>
        </li>
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
    {% set count = s.number_faculty %}
    {% if count > 0 %}
        <span class="label label-primary">{{ count }} available</span>
    {% else %}
        <span class="label label-danger">No availability</span>
    {% endif %}
{% else %}
    <span class="label label-default">Not yet requested</span>
{% endif %}
"""


def assessment_sessions_data(sessions):

    data = [{'date': render_template_string(_date, s=s),
             'session': s.session_type_label,
             'rooms': render_template_string(_rooms, s=s),
             'availability': render_template_string(_faculty, s=s),
             'menu': render_template_string(_menu, s=s)} for s in sessions]

    return jsonify(data)
