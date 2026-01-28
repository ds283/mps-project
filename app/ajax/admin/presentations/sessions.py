#
# Created by David Seery on 2018-09-30.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import calendar

from flask import jsonify, get_template_attribute, current_app, render_template
from jinja2 import Template, Environment

# language=jinja2
_date = """
{{ s.date_as_string }}
{% if s.has_issues %}
    <i class="fas fa-exclamation-triangle text-danger"></i>
    {% set errors = s.errors %}
    {% set warnings = s.warnings %}
    <div class="mt-1">
        {% if errors|length == 1 %}
            <span class="badge bg-danger">1 error</span>
        {% elif errors|length > 1 %}
            <span class="badge bg-danger">{{ errors|length }} errors</span>
        {% endif %}
        {% if warnings|length == 1 %}
            <span class="badge bg-warning text-dark">1 warning</span>
        {% elif warnings|length > 1 %}
            <span class="badge bg-warning text-dark">{{ warnings|length }} warnings</span>
        {% endif %}
        {% if errors|length > 0 %}
            {% for item in errors %}
                {% if loop.index <= 5 %}
                    <div class="text-danger small">{{ item }}</div>
                {% elif loop.index == 6 %}
                    <div class="text-danger small">Further errors suppressed...</div>
                {% endif %}            
            {% endfor %}
        {% endif %}
        {% if warnings|length > 0 %}
            {% for item in warnings %}
                {% if loop.index <= 5 %}
                    <div class="text-warning small">Warning: {{ item }}</div>
                {% elif loop.index == 6 %}
                    <div class="text-warning small">Further warnings suppressed...</div>
                {% endif %}
            {% endfor %}
        {% endif %}
    </div>
{% endif %}
"""


# language=jinja2
_rooms = """
{% for room in s.ordered_rooms %}
    {{ simple_label(room.label) }}
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> No rooms attached</span>
{% endfor %}
"""


# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% set a = s.owner %}
        {% set disabled = not s.owner.is_feedback_open %}
        <div class="dropdown-header">Edit session</div>
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.edit_session', id=s.id) }}"{% endif %}>
            <i class="fas fa-sliders-h fa-fw"></i> Settings...
        </a>
        {% set disabled = (not a.requested_availability and not a.skip_availability) or a.is_deployed %}
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.submitter_session_availability', id=s.id) }}"{% endif %}>
            <i class="fas fa-cogs fa-fw"></i> Submitters...
        </a>
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.assessor_session_availability', id=s.id) }}"{% endif %}>
            <i class="fas fa-cogs fa-fw"></i> Assessors...
        </a>
        {% set disabled = not a.is_feedback_open %}
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.delete_session', id=s.id) }}"{% endif %}>
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    </div>
</div>
"""


# language=jinja2
_availability = """
<div class="d-flex flex-column gap-1 justify-content-start align-items-start">
    {% set lifecycle = s.owner.availability_lifecycle %}
    {% if lifecycle <= s.owner.AVAILABILITY_NOT_REQUESTED %}
        <span class="small text-secondary">Not yet requested</span>
    {% else %}
        {% if lifecycle == s.owner.AVAILABILITY_SKIPPED %}
            <span class="small text-secondary">Availability skipped</span>
        {% endif %}
        {% set fac_available = s.number_available_faculty %}
        {% set fac_ifneeded = s.number_ifneeded_faculty %}
        {% set fac_unavailable = s.number_unavailable_faculty %}
        {% if fac_available > 0 or fac_ifneeded > 0 %}
            <div class="d-flex flex-row gap-1 justify-content-left align-items-start">
                <span class="small text-success">{{ fac_available }} available</span>
                {% if fac_ifneeded > 0 %}
                    <span class="small text-secondary">|</span><span class="small text-secondary">{{ fac_ifneeded }} if-needed</span>
                {% endif %}
                {% if fac_unavailable > 0 %}
                    <span class="small text-secondary">|</span><span class="small text-danger">{{ fac_unavailable }} unavailable</span>
                {% endif %}
                <span class="small text-secondary">|</span><span class="small text-secondary">Total {{ fac_available + fac_ifneeded }}</span>
            </div>
        {% else %}
            <span class="small fw-semibold text-danger">No availability</span>
        {% endif %}
        {% set sub_unavailable = s.number_unavailable_submitters %}
        {% if sub_unavailable > 0 %}
            {% set pl = 's' %}
            {% if sub_unavailable == 1 %}{% set pl = '' %}{% endif %}
            <span class="small text-danger">{{ sub_unavailable }} submitter{{ pl }} unavailable</span>
        {% else %}
            <span class="small text-primary">All submitters available</span>
        {% endif %}
    {% endif %}
</div>
"""


# language=jinja2
_session = """
{{ unformatted_label(s.session_type_label, user_classes="fw-semibold text-secondary") }}
"""


def _build_date_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_date)


def _build_session_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_session)


def _build_rooms_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_rooms)


def _build_availability_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_availability)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def assessment_sessions_data(sessions):
    simple_label = get_template_attribute("labels.html", "simple_label")
    unformatted_label = get_template_attribute("labels.html", "unformatted_label")

    date_templ: Template = _build_date_templ()
    session_templ: Template = _build_session_templ()
    rooms_templ: Template = _build_rooms_templ()
    availability_templ: Template = _build_availability_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "date": {"display": render_template(date_templ, s=s), "timestamp": calendar.timegm(s.date.timetuple())},
            "session": render_template(session_templ, s=s, unformatted_label=unformatted_label),
            "rooms": render_template(rooms_templ, s=s, simple_label=simple_label),
            "availability": render_template(availability_templ, s=s),
            "menu": render_template(menu_templ, s=s),
        }
        for s in sessions
    ]

    return jsonify(data)
