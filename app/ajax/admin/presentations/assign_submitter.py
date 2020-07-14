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


_name = \
"""
{{ s.session.label|safe }}
{% if not s.is_valid %}
    <i class="fa fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
"""


_assessors = \
"""
{% set rec = s.owner %}
{% for assessor in s.assessors %}
    <div>
        <div class="dropdown schedule-assign-button" style="display: inline-block;">
            <a class="badge badge-secondary" data-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                {{ assessor.user.name }}
                {% set count = rec.get_number_faculty_slots(assessor.id) %}
                ({{ count }})
            </a>
            <div class="dropdown-menu">
                <a class="dropdown-item" href="{{ url_for('admin.schedule_adjust_assessors', id=s.id, url=url, text=text) }}">
                    Reassign assessors...
                </a>
            </div>
        </div>
        {% if s.session.faculty_ifneeded(assessor.id) %}
            <span class="badge badge-warning">if-needed</span>
        {% elif s.session.faculty_unavailable(assessor.id) %}
            <i class="fa fa-exclamation-triangle" style="color:red;"></i>
        {% endif %}
    </div>
{% endfor %}
<div>
{% if s.presenter_has_overlap(t) %}
    <span class="badge badge-success"><i class="fa fa-check"></i> Pool overlap</span>
{% else %}
    <span class="badge badge-danger"><i class="fa fa-times"></i> No pool overlap</span>
{% endif %}
</div>
"""


_talks = \
"""
{% macro truncate_name(name) %}
    {% if name|length > 18 %}
        {{ name[0:18] }}...
    {% else %}
        {{ name }}
    {% endif %}
{% endmacro %}
{% set ns = namespace(count=0) %}
{% for talk in s.talks %}
    {% set ns.count = ns.count + 1 %}
    <div class="dropdown schedule-assign-button" style="display: inline-block;">
        {% set style = talk.pclass.make_CSS_style() %}
        <a class="badge {% if style %}badge-secondary{% else %}badge-info{% endif %}" {% if style %}style="{{ style }}"{% endif %} data-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
            {{ talk.owner.student.user.last_name }}
            ({{ talk.project.owner.user.last_name }} &ndash; {{ truncate_name(talk.project.name) }})
        </a>
        <div class="dropdown-menu">
            <a class="dropdown-item" href="{{ url_for('admin.schedule_adjust_submitter', slot_id=s.id, talk_id=talk.id, url=url, text=text) }}">
                Reassign presentation...
            </a>
        </div>
    </div>
    {% if s.session.submitter_unavailable(talk.id) %}
        <i class="fa fa-exclamation-triangle" style="color:red;"></i>
    {% endif %}
{% endfor %}
{% if not s.is_valid %}
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


_menu = \
"""
<div class="float-right">
    <a href="{{ url_for('admin.schedule_move_submitter', old_id=old_slot.id, new_id=new_slot.id, talk_id=talk.id, url=back_url, text=back_text) }}" class="btn btn-secondary btn-sm">
        <i class="fa fa-arrows"></i> Move
    </a>
</div>
"""


def assign_submitter_data(slots, old_slot, talk, url=None, text=None):
    data = [{'session': {'display': render_template_string(_name, s=s),
                         'sortvalue': s.session.date.isoformat()},
             'room': s.room.label,
             'assessors': render_template_string(_assessors, s=s, t=talk, url=url, text=text),
             'talks': render_template_string(_talks, s=s, url=url, text=text),
             'menu': render_template_string(_menu, old_slot=old_slot, new_slot=s, talk=talk, back_url=url, back_text=text)} for s in slots]

    return jsonify(data)
