#
# Created by David Seery on 2018-09-28.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, get_template_attribute, current_app, render_template
from jinja2 import Template, Environment

# language=jinja2
_name = """
{% set state = a.availability_lifecycle %}
{% if state >= a.AVAILABILITY_CLOSED %}
    <a class="text-decoration-none" href="{{ url_for('admin.assessment_schedules', id=a.id) }}">{{ a.name }}</a>
{% else %}
    <a class="text-decoration-none" href="{{ url_for('admin.assessment_manage_sessions', id=a.id) }}">{{ a.name }}</a>
{% endif %}
{% if a.has_issues %}
    <i class="fas fa-exclamation-triangle text-danger"></i>
{% endif %}
<div class="mt-1 d-flex flex-column justify-content-start align-items-start">
    {% if a.is_deployed %}
        <span class="small text-success"><i class="fas fa-check"></i> Deployed</span>
    {% endif %}
    {% if not a.is_feedback_open %}
        <span class="small text-success">Feedback closed</span>
    {% endif %}
    {% if state == a.AVAILABILITY_NOT_REQUESTED %}
        <span class="small text-secondary">Availability not requested</span>
    {% elif state == a.AVAILABILITY_REQUESTED %}
        <span class="small text-success"><i class="fas fa-check-circle"></i> Availability requested</span>
        {% set num_outstanding = a.availability_outstanding_count %}
        {% if num_outstanding > 0 %}
            <span class="small text-secondary">{{ num_outstanding }} outstanding requests</span>
        {% endif %}
    {% elif state == a.AVAILABILITY_CLOSED %}
        <span class="small text-secondary"><i class="fas fa-check-circle"></i> Availability closed</span>
    {% elif state == a.AVAILABILITY_SKIPPED %}
        <span class="small text-secondary"><i class="fas fa-times-circle"></i> Availability skipped</span>
    {% else %}
        <span class="small fw-semibold text-danger">Unknown lifecycle state</span>
    {% endif %}
    {% set sessions = a.number_sessions %}
    {% set pl = 's' %}{% if sessions == 1 %}{% set pl = '' %}{% endif %}
    <span class="small text-secondary">{{ sessions }} session{{ pl }}</span>
    {% set slots = a.number_slots %}
    {% set pl = 's' %}{% if slots == 1 %}{% set pl = '' %}{% endif %}
    <span class="small text-secondary">{{ slots }} slot{{ pl }}</span>
    {% set schedules = a.number_schedules %}
    {% set pl = 's' %}{% if schedules == 1 %}{% set pl = '' %}{% endif %}
    <span class="small text-secondary">{{ schedules }} schedule{{ pl }}</span>
</div>
"""


# language=jinja2
_periods = """
{% for period in a.submission_periods %}
    <div style="d-flex flex-column gap-1 justify-content-start align-items-start">
        {{ unformatted_label(period.label, user_classes="fw-semibold text-secondary", tag="div") }}
        {% set num = period.number_submitters %}
        {% set pl = 's' %}
        {% if num == 1 %}{% set pl = '' %}{% endif %}
        <span class="small text-muted">{{ num }} presentation{{ pl }}</span>
    </div>
{% endfor %}
{% set total = a.number_talks %}
{% set missing = a.number_not_attending %}
{% if total > 0 or missing > 0 %}
    <div class="mt-1 d-flex flex-column gap-1 justify-content-start align-items-start">
        {% set pl = 's' %}{% if total == 1 %}{% set p = '' %}{% endif %}
        <span class="small text-primary"><span class="fw-semibold">{{ total }}</span> total presentation{{ pl }}</span>
        {% if missing > 0 %}
            <span class="small text-danger"><span class="fw-semibold">{{ missing }}</span> not attending</span>
        {% endif %}
    </div>
{% endif %}
"""


# language=jinja2
_sessions = """
{% set sessions = a.ordered_sessions.all() %}
<div class="d-flex flex-column gap-2 justify-content-start align-items-start">
    {% for session in sessions %}
        {% if a.requested_availability %}
            <div style="d-flex flex-row gap-2 justify-content-start align-items-start">
                <span><i class="fas fa-calendar text-success"></i> {{ unformatted_label(session.label, user_classes="text-secondary fw-semibold") }}</span>
                {% set available = session.number_available_faculty %}
                {% set ifneeded = session.number_ifneeded_faculty %}
                <span class="small text-success"><span class="fw-semibold">{{ available }}{% if ifneeded > 0 %}(+{{ ifneeded }}){% endif %}</span> available</span>
            </div>
        {% else %}
            <span><i class="fas fa-calendar text-success"></i> {{ unformatted_label(session.label, user_classes="text-secondary") }}</span>
        {% endif %}
    {% endfor %}
</div>
{% if a.has_issues %}
    {% set errors = a.errors %}
    {% set warnings = a.warnings %}
    <div class="mt-1 d-flex flex-column justify-content-start align-items-start">
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
                {% if loop.index <= 10 %}
                    <div class="text-danger small">{{ item }}</div>
                {% elif loop.index == 11 %}
                    <div class="text-danger small">Further errors suppressed...</div>
                {% endif %}            
            {% endfor %}
        {% endif %}
        {% if warnings|length > 0 %}
            {% for item in warnings %}
                {% if loop.index <= 10 %}
                    <div class="text-secondary small">Warning: {{ item }}</div>
                {% elif loop.index == 11 %}
                    <div class="text-secondary small">Further warnings suppressed...</div>
                {% endif %}
            {% endfor %}
        {% endif %}
    </div>
{% endif %}
"""


# language=jinja2
_menu = """
{% set requested_availability = a.requested_availability %}
{% set skipped_availability = a.skip_availability %}
{% set availability_closed = a.availability_closed %}
{% set deployed = a.is_deployed %}
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <div class="dropdown-header">Scheduling</div>
        {% set valid = a.is_valid %}
        {% set disabled = (not valid) or a.availability_lifecycle == a.AVAILABILITY_SKIPPED %}
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.initialize_assessment', id=a.id) }}"{% endif %}>
            <i class="fas fa-calendar fa-fw"></i> Initialize...
        </a>
        {% set disabled = not availability_closed and not skipped_availability %}
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.assessment_schedules', id=a.id) }}"{% endif %}>
            <i class="fas fa-wrench fa-fw"></i> Schedules...
        </a>
        
        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Edit assessment</div>
        {% set disable_submitters = not requested_availability and not skipped_availability %}
        {% set disable_assessors = not requested_availability and not skipped_availability %}
        {% set disable_delete = deployed %}
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_assessment', id=a.id) }}">
            <i class="fas fa-sliders-h fa-fw"></i> Settings...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.assessment_manage_sessions', id=a.id) }}">
            <i class="fas fa-calendar fa-fw"></i> Sessions...
        </a>
        <a class="dropdown-item d-flex gap-2 {% if disable_submitters %}disabled{% endif %}"{% if not disable_submitters %}href="{{ url_for('admin.assessment_manage_attendees', id=a.id) }}"{% endif %}>
            <i class="fas fa-user-circle fa-fw"></i> Submitters...
        </a>
        <a class="dropdown-item d-flex gap-2 {% if disable_assessors %}disabled{% endif %}"{% if not disable_assessors %}href="{{ url_for('admin.assessment_manage_assessors', id=a.id) }}"{% endif %}>
            <i class="fas fa-user-circle fa-fw"></i> Assessors...
        </a>
        <a class="dropdown-item d-flex gap-2 {% if disable_delete %}disabled{% endif %}"{% if not disable_delete %}href="{{ url_for('admin.delete_assessment', id=a.id) }}"{% endif %}>
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
        
        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Administration</div>
        {% set disabled = not a.is_closable %}
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.close_assessment', id=a.id) }}"{% endif %}>
            <i class="fas fa-times-circle fa-fw"></i> Close feedback
        </a>
    </div>
</div>
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_periods_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_periods)


def _build_sessions_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_sessions)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def presentation_assessments_data(assessments):
    unformatted_label = get_template_attribute("labels.html", "unformatted_label")

    name_templ: Template = _build_name_templ()
    periods_templ: Template = _build_periods_templ()
    sessions_templ: Template = _build_sessions_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "name": render_template(name_templ, a=a),
            "periods": render_template(periods_templ, a=a, unformatted_label=unformatted_label),
            "sessions": render_template(sessions_templ, a=a, unformatted_label=unformatted_label),
            "menu": render_template(menu_templ, a=a),
        }
        for a in assessments
    ]

    return jsonify(data)
