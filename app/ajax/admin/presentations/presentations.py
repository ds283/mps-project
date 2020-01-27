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
{% set state = a.availability_lifecycle %}
{% if state >= a.AVAILABILITY_CLOSED %}
    <a href="{{ url_for('admin.assessment_schedules', id=a.id) }}">{{ a.name }}</a>
{% else %}
    <a href="{{ url_for('admin.assessment_manage_sessions', id=a.id) }}">{{ a.name }}</a>
{% endif %}
{% if not a.is_valid %}
    <i class="fa fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
<p></p>
{% if a.is_deployed %}
    <span class="label label-success"><i class="fa fa-check"></i> Deployed</span>
{% endif %}
{% if not a.feedback_open %}
    <span class="label label-success">Feedback closed</span>
{% endif %}
{% if state == a.AVAILABILITY_NOT_REQUESTED %}
    <span class="label label-default">Availability not requested</span>
{% elif state == a.AVAILABILITY_REQUESTED %}
    <span class="label label-success">Availability requested</span>
    {% set num_outstanding = a.availability_outstanding_count %}
    {% if num_outstanding > 0 %}
        <span class="label label-info">{{ num_outstanding }} outstanding</span>
    {% endif %}
{% elif state == a.AVAILABILITY_CLOSED %}
    <span class="label label-primary">Availability closed</span>
{% else %}
    <span class="label label-danger">Unknown lifecycle state</span>
{% endif %}
{% set sessions = a.number_sessions %}
{% set pl = 's' %}{% if sessions == 1 %}{% set pl = '' %}{% endif %}
<span class="label label-info">{{ sessions }} session{{ pl }}</span>
{% set slots = a.number_slots %}
{% set pl = 's' %}{% if slots == 1 %}{% set pl = '' %}{% endif %}
<span class="label label-info">{{ slots }} slot{{ pl }}</span>
{% set schedules = a.number_schedules %}
{% set pl = 's' %}{% if schedules == 1 %}{% set pl = '' %}{% endif %}
<span class="label label-info">{{ schedules }} schedule{{ pl }}</span>
"""


_periods = \
"""
{% for period in a.submission_periods %}
    <div style="display: inline-block;">
        {{ period.label|safe }}
        {% set num = period.number_projects %}
        {% set pl = 's' %}
        {% if num == 1 %}{% set pl = '' %}{% endif %}
        <span class="label label-info">{{ num }} project{{ pl }}</span>
    </div>
{% endfor %}
{% set total = a.number_talks %}
{% set missing = a.number_not_attending %}
{% if total > 0 or missing > 0 %}
    <p></p>
    {% set pl = 's' %}{% if total == 1 %}{% set p = '' %}{% endif %}
    <span class="label label-primary">{{ total }} presentation{{ pl }}</span>
    {% if missing > 0 %}
        <span class="label label-warning">{{ missing }} not attending</span>
    {% else %}
        <span class="label label-success">{{ missing }} not attending</span>
    {% endif %}
{% endif %}
"""


_sessions = \
"""
{% set sessions = a.ordered_sessions.all() %}
{% for session in sessions %}
    {% if a.requested_availability %}
        <div style="display: inline-block;">
            {{ session.label|safe }}
            {% set available = session.number_available_faculty %}
            {% set ifneeded = session.number_ifneeded_faculty %}
            <span class="label label-info">{{ available }}{% if ifneeded > 0 %}(+{{ ifneeded }}){% endif %} available</span>
        </div>
    {% else %}
        {{ session.label|safe }}
    {% endif %}
{% endfor %}
{% if not a.is_valid %}
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
                    <p class="help-block">Warning: {{ item }}</p>
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
        <li class="dropdown-header">Scheduling</li>
        {% set valid = a.is_valid %}
        {% set disabled = not valid and a.availability_lifecycle < a.AVAILABILITY_REQUESTED %}
        <li {% if disabled %}class="disabled"{% endif %}>
            <a {% if not disabled %}href="{{ url_for('admin.assessment_availability', id=a.id) }}"{% endif %}>
                <i class="fa fa-calendar"></i> Assessor availability...
            </a>
        </li>
        {% set disabled = not a.availability_closed %}
        <li {% if disabled %}class="disabled"{% endif %}>
            <a {% if not disabled %}href="{{ url_for('admin.assessment_schedules', id=a.id) }}"{% endif %}>
                <i class="fa fa-wrench"></i> Edit schedules...
            </a>
        </li>
        
        <li role="separator" class="divider">
        <li class="dropdown-header">Edit assessment</li>
        {% set requested_availability = a.requested_availability %}
        {% set deployed = a.is_deployed %}
        {% set disable_settings = requested_availability %}
        {% set disable_submitters = not requested_availability %}
        {% set disable_assessors = not requested_availability %}
        {% set disable_delete = deployed %}
        <li {% if disable_settings %}class="disabled"{% endif %}>
            <a {% if not disable_settings %}href="{{ url_for('admin.edit_assessment', id=a.id) }}"{% endif %}>
                <i class="fa fa-cogs"></i> Settings...
            </a>
        </li>
        <li>
            <a href="{{ url_for('admin.assessment_manage_sessions', id=a.id) }}">
                <i class="fa fa-calendar"></i> Sessions...
            </a>
        </li>
        <li {% if disable_submitters %}class="disabled"{% endif %}>
            <a {% if not disable_submitters %}href="{{ url_for('admin.assessment_manage_attendees', id=a.id) }}"{% endif %}>
                <i class="fa fa-user"></i> Submitters...
            </a>
        </li>
        <li {% if disable_assessors %}class="disabled"{% endif %}>
            <a {% if not disable_assessors %}href="{{ url_for('admin.assessment_manage_assessors', id=a.id) }}"{% endif %}>
                <i class="fa fa-user"></i> Assessors...
            </a>
        </li>
        <li {% if disable_delete %}class="disabled"{% endif %}>
            <a {% if not disable_delete %}href="{{ url_for('admin.delete_assessment', id=a.id) }}"{% endif %}>
                <i class="fa fa-trash"></i> Delete
            </a>
        </li>
        
        <li role="separator" class="divider">
        <li class="dropdown-header">Administration</li>
        {% set disabled = not a.is_closable %}
        <li {% if disabled %}class="disabled"{% endif %}>
            <a {% if not disabled %}href="{{ url_for('admin.close_assessment', id=a.id) }}"{% endif %}>
                <i class="fa fa-times-circle"></i> Close feedback
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
