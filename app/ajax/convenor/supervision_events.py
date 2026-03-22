#
# Created by David Seery on 22/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List

from flask import current_app, render_template, url_for
from jinja2 import Environment, Template

from ...models import SupervisionEvent, SupervisionEventTemplate

# language=jinja2
_name = """
<div class="fw-semibold">
    {% if event.sub_record and event.sub_record.owner and event.sub_record.owner.student %}
        {{ event.sub_record.owner.student.user.name }}
    {% else %}
        <span class="text-muted">Unknown student</span>
    {% endif %}
</div>
<div class="small text-muted">{{ event.name }}</div>
<div class="d-flex flex-row flex-wrap justify-content-start align-items-center gap-2 mt-2">
    {% if event.meeting_summary and event.meeting_summary|length > 0 %}
        <span class="badge bg-success"><i class="fas fa-check me-1"></i>Summary</span>
    {% endif %}
    {% if event.supervision_notes and event.supervision_notes|length > 0 %}
        <span class="badge bg-success"><i class="fas fa-check me-1"></i>Supervisor notes</span>
    {% endif %}
    {% if event.submitter_notes and event.submitter_notes|length > 0 %}
        <span class="badge bg-success"><i class="fas fa-check me-1"></i>Submitter notes</span>
    {% endif %}
    {% if event.uploaded_assets.count() > 0 %}
        <span class="badge bg-success"><i class="fas fa-check me-1"></i>Assets</span>
    {% endif %}
</div>
"""

# language=jinja2
_attendees = """
<div class="d-flex flex-column gap-1">
    {% if event.owner and event.owner.user %}
        <div class="small">
            <span class="badge bg-primary me-1">Owner</span><i class="fas fa-user me-1"></i>{{ event.owner.user.name }}
        </div>
    {% endif %}
    {% for role in event.team %}
        {% if role.user %}
            <div class="small">
                <span class="badge bg-secondary me-1">Team</span><i class="fas fa-user me-1"></i>{{ role.user.name }}
            </div>
        {% endif %}
    {% endfor %}
    {% if not event.owner or not event.owner.user %}
        <span class="text-muted small">No attendees</span>
    {% endif %}
</div>
"""

# language=jinja2
_datetime = """
{% if event.time is not none %}
    <div><i class="fas fa-clock fa-fw"></i> {{ event.time.strftime("%a %d %b %Y %H:%M") }}</div>
{% else %}
    <div><span class="text-muted small">Date/time not set</span></div>
{% endif %}
{% if event.location is not none and event.location|length > 0 %}
    <div class="small text-muted mt-1"><i class="fas fa-map-marker-alt fa-fw"></i> {{ event.location }}</div>
{% endif %}
"""

# language=jinja2
_attendance = """
{% if event.monitor_attendance %}
    {% if attendance_label is not none %}
        {% if event.attendance == event.ATTENDANCE_ON_TIME or event.attendance == event.ATTENDANCE_LATE %}
            <span class="text-success"><i class="fas fa-check-circle"></i> {{ attendance_label }}</span>
        {% elif event.attendance == event.ATTENDANCE_NO_SHOW_UNNOTIFIED %}
            <span class="text-danger"><i class="fas fa-exclamation-circle"></i> {{ attendance_label }}</span>
        {% elif event.attendance == event.ATTENDANCE_NO_SHOW_NOTIFIED %}
            <span class="text-danger"><i class="fas fa-info-circle"></i> {{ attendance_label }}</span>
        {% else %}
            <span class="text-secondary">{{ attendance_label }}</span>
        {% endif %}
    {% else %}
        <span class="badge bg-secondary">Not recorded</span>
    {% endif %}
{% else %}
    <span class="text-muted small">Not monitored</span>
{% endif %}
"""

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle table-button" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('projecthub.event_details', event_id=event.id, url=return_url) }}">
            <i class="fas fa-eye fa-fw"></i> View/edit details&hellip;
        </a>
    </div>
</div>
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_attendees_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_attendees)


def _build_datetime_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_datetime)


def _build_attendance_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_attendance)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def supervision_events_data(
    events: List[SupervisionEvent],
    template: SupervisionEventTemplate,
    url: str = None,
    text: str = None,
):
    return_url = url_for(
        "convenor.inspect_template_events", template_id=template.id, url=url, text=text
    )

    name_templ: Template = _build_name_templ()
    attendees_templ: Template = _build_attendees_templ()
    datetime_templ: Template = _build_datetime_templ()
    attendance_templ: Template = _build_attendance_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "name": render_template(name_templ, event=e),
            "attendees": render_template(attendees_templ, event=e),
            "datetime": {
                "display": render_template(datetime_templ, event=e),
                "sortvalue": e.time.isoformat() if e.time is not None else "",
            },
            "attendance": render_template(
                attendance_templ,
                event=e,
                attendance_label=SupervisionEvent._attendance_string.get(e.attendance)
                if e.attendance is not None
                else None,
            ),
            "menu": render_template(menu_templ, event=e, return_url=return_url),
        }
        for e in events
    ]

    return data
