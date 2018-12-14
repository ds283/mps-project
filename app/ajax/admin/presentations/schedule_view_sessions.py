#
# Created by David Seery on 2018-10-18.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify
from ....models import PresentationSession


_name = \
"""
{{ s.session.label|safe }}
{% if not s.is_valid %}
    <i class="fa fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
"""


_assessors = \
"""
{% for assessor in s.assessors %}
    <div>
        <div class="dropdown schedule-assign-button" style="display: inline-block;">
            <a class="label label-default" type="button" data-toggle="dropdown">
                {{ assessor.user.name }}
                <span class="caret"></span>
            </a>
            <ul class="dropdown-menu">
                <li>
                    <a href="{{ url_for('admin.schedule_adjust_assessors', id=s.id, url=url_for('admin.schedule_view_sessions', id=rec.id, url=back_url, text=back_text), text='schedule inspector sessions view') }}">
                        Reassign assessors...
                    </a>
                </li>
            </ul>
        </div>
        {% if s.session.faculty_ifneeded(assessor.id) %}
            <span class="label label-warning">if-needed</span>
        {% elif s.session.faculty_unavailable(assessor.id) %}
            <i class="fa fa-exclamation-triangle" style="color:red;"></i>
        {% endif %}
    </div>
{% endfor %}
"""


_talks = \
"""
{% set ns = namespace(count=0) %}
{% for talk in s.talks %}
    {% set ns.count = ns.count + 1 %}
    <div class="dropdown schedule-assign-button" style="display: inline-block;">
        {% set style = talk.pclass.make_CSS_style() %}
        <a class="label {% if style %}label-default{% else %}label-info{% endif %} dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} type="button" data-toggle="dropdown">
            {{ talk.owner.student.user.name }}
            <span class="caret"></span>
        </a>
        <ul class="dropdown-menu">
            <li>
                <a href="{{ url_for('admin.schedule_adjust_submitter', slot_id=s.id, talk_id=talk.id, url=url_for('admin.schedule_view_sessions', id=rec.id, url=back_url, text=back_text), text='schedule inspector sessions view') }}">
                    Reassign presentation...
                </a>
            </li>
        </ul>
    </div>
    {% if s.session.submitter_unavailable(talk.id) %}
        <i class="fa fa-exclamation-triangle" style="color:red;"></i>
    {% endif %}
{% endfor %}
{% if ns.count > 0 %}
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


_room = \
"""
{% set style = s.room.building.make_CSS_style() %}
<div class="dropdown schedule-assign-button">
    <a class="label {% if style is none %}label-info{% else %}label-default{% endif %} dropdown" {% if style %}style="{{ style }}"{% endif %} type="button" data-toggle="dropdown">
        {{ s.room.full_name }}
        <span class="caret"></span>
    </a>
    <ul class="dropdown-menu">
        <li class="dropdown-header">Alternative venues</li>
        {% set rooms = s.alternative_rooms %}
        {% for room in rooms %}
            <li>
                <a href="{{ url_for('admin.schedule_move_room', slot_id=s.id, room_id=room.id) }}">
                    {{ room.full_name }}
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a><i class="fa fa-bar"></i> None available</a>
            </li>
        {% endfor %}
    </ul>
</div>
"""


def schedule_view_sessions(slots, record, url=None, text=None):
    data = [{'session': {'display': render_template_string(_name, s=s),
                         'sortvalue': s.session.date.isoformat()+('-AA' if s.session.session_type == PresentationSession.MORNING_SESSION else '-BB')},
             'room': render_template_string(_room, s=s),
             'assessors': render_template_string(_assessors, s=s, rec=record, back_url=url, back_text=text),
             'talks': render_template_string(_talks, s=s, rec=record, back_url=url, back_text=text)} for s in slots]

    return jsonify(data)
