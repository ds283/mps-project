#
# Created by David Seery on 2018-10-18.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, get_template_attribute
from ....models import PresentationSession


# language=jinja2
_name = """
<div>
    {{ simple_label(s.session.label) }}
    {% if s.has_issues %}
        <i class="fas fa-exclamation-triangle text-danger"></i>
    {% endif %}
</div>
{% if s.is_empty %}
    <div class="mt-1">
        <a href="btn btn-sm btn-outline-danger" href="{{ url_for('admin.schedule_delete_slot', id=s.id, url=url_for('admin.schedule_view_sessions', id=rec.id, url=back_url, text=back_text), text='schedule inspector sessions view') }}">
            Delete slot
        </a>
    </div>
{% endif %}
"""


# language=jinja2
_assessors = """
{% for assessor in s.assessors %}
    <div>
        <div class="dropdown schedule-assign-button" style="display: inline-block;">
            <a class="badge text-decoration-none text-nohover-dark bg-light" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                {{ assessor.user.name }}
            </a>
            <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.schedule_adjust_assessors', id=s.id, url=url_for('admin.schedule_view_sessions', id=rec.id, url=back_url, text=back_text), text='schedule inspector sessions view') }}">
                    Reassign assessors...
                </a>
            </div>
        </div>
        {% if s.session.faculty_ifneeded(assessor.id) %}
            <span class="badge bg-warning text-dark">If needed</span>
        {% elif s.session.faculty_unavailable(assessor.id) %}
            <i class="fas fa-exclamation-triangle text-danger"></i>
        {% endif %}
    </div>
{% else %}
    <div>
        <a class="badge bg-warning text-nohover-dark text-decoration-none" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
            None assigned
        </a>
        <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.schedule_adjust_assessors', id=s.id, url=url_for('admin.schedule_view_sessions', id=rec.id, url=back_url, text=back_text), text='schedule inspector sessions view') }}">
                Reassign assessors...
            </a>
        </div>
        <i class="fas fa-exclamation-triangle text-danger"></i>
    </div>
{% endfor %}
"""


# language=jinja2
_talks = """
{% set ns = namespace(count=0) %}
{% for talk in s.talks %}
    {% set ns.count = ns.count + 1 %}
    <div class="dropdown schedule-assign-button" style="display: inline-block;">
        {% set style = talk.pclass.make_CSS_style() %}
        <a class="badge text-decoration-none text-nohover-light {% if style %}bg-secondary{% else %}bg-info{% endif %} dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
            {{ talk.owner.student.user.name }}
        </a>
        <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.schedule_adjust_submitter', slot_id=s.id, talk_id=talk.id, url=url_for('admin.schedule_view_sessions', id=rec.id, url=back_url, text=back_text), text='schedule inspector sessions view') }}">
                Reassign presentation...
            </a>
        </div>
    </div>
    {% if s.session.submitter_unavailable(talk.id) %}
        <i class="fas fa-exclamation-triangle text-danger"></i>
    {% endif %}
{% endfor %}
{% if ns.count > 0 %}
    <p></p>
    {% set errors = s.errors %}
    {% set warnings = s.warnings %}
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
                <div class="text-warning small">Warning: {{ item }}</div>
            {% elif loop.index == 11 %}
                <div class="text-warning small">Further warnings suppressed...</div>
            {% endif %}
        {% endfor %}
    {% endif %}
{% endif %}
"""


# language=jinja2
_room = """
{% set style = s.room.building.make_CSS_style() %}
<div class="dropdown schedule-assign-button">
    <a class="badge text-decoration-none text-nohover-light {% if style is none %}bg-info{% else %}bg-secondary{% endif %} dropdown" {% if style %}style="{{ style }}"{% endif %} data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
        {{ s.room.full_name }}
    </a>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
        <div class="dropdown-header">Alternative venues</div>
        {% set rooms = s.alternative_rooms %}
        {% for room in rooms %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.schedule_move_room', slot_id=s.id, room_id=room.id) }}">
                {{ room.full_name }}
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-bar fa-fw"></i> None available</a>
        {% endfor %}
    </ul>
</div>
"""


def schedule_view_sessions(slots, record, url=None, text=None):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [
        {
            "session": {
                "display": render_template_string(_name, s=s, simple_label=simple_label),
                "sortvalue": s.session.date.isoformat() + ("-AA" if s.session.session_type == PresentationSession.MORNING_SESSION else "-BB"),
            },
            "room": render_template_string(_room, s=s),
            "assessors": render_template_string(_assessors, s=s, rec=record, back_url=url, back_text=text),
            "talks": render_template_string(_talks, s=s, rec=record, back_url=url, back_text=text),
        }
        for s in slots
    ]

    return jsonify(data)
