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

# language=jinja2
_name = \
"""
{{ simple_label(s.session.label) }}
{% if s.has_issues %}
    <i class="fas fa-exclamation-triangle text-danger"></i>
{% endif %}
"""


# language=jinja2
_assessors = \
"""
{% set rec = s.owner %}
{% for assessor in s.assessors %}
    <div>
        <div class="dropdown schedule-assign-button" style="display: inline-block;">
            <a class="badge text-decoration-none text-nohover-light bg-secondary" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                {{ assessor.user.name }}
                {% set count = rec.get_number_faculty_slots(assessor.id) %}
                ({{ count }})
            </a>
            <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.schedule_adjust_assessors', id=s.id, url=url, text=text) }}">
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
{% endfor %}
<div>
{% if s.presenter_has_overlap(t) %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Pool overlap</span>
{% else %}
    <span class="badge bg-danger"><i class="fas fa-times"></i> No pool overlap</span>
{% endif %}
</div>
"""


# language=jinja2
_talks = \
"""
{% macro truncate_name(name, maxlength=25) %}
    {%- if name|length > maxlength -%}
        {{ name[0:maxlength] }}...
    {%- else -%}
        {{ name }}
    {%- endif -%}
{% endmacro %}
{% set ns = namespace(count=0) %}
{% for talk in s.talks %}
    {% set ns.count = ns.count + 1 %}
    <div class="dropdown schedule-assign-button" style="display: inline-block;">
        {% set style = talk.pclass.make_CSS_style() %}
        <a class="badge text-decoration-none text-nohover-light {% if style %}bg-secondary{% else %}bg-info{% endif %}" {% if style %}style="{{ style }}"{% endif %} data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
            {{ talk.owner.student.user.last_name }}
            ({{ talk.project.owner.user.last_name }} &ndash; {{ truncate_name(talk.project.name) }})
        </a>
        <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.schedule_adjust_submitter', slot_id=s.id, talk_id=talk.id, url=url, text=text) }}">
                Reassign presentation...
            </a>
        </div>
    </div>
    {% if s.session.submitter_unavailable(talk.id) %}
        <i class="fas fa-exclamation-triangle text-danger"></i>
    {% endif %}
{% endfor %}
{% if s.has_issues %}
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
_menu = \
"""
<div class="float-end">
    <a href="{{ url_for('admin.schedule_move_submitter', old_id=old_slot.id, new_id=new_slot.id, talk_id=talk.id, url=back_url, text=back_text) }}" class="btn btn-outline-secondary btn-sm">
        <i class="fas fa-arrow-alt-circle-right"></i> Move
    </a>
</div>
"""


def assign_submitter_data(slots, old_slot, talk, url=None, text=None):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [{'session': {'display': render_template_string(_name, s=s, simple_label=simple_label),
                         'sortvalue': s.session.date.isoformat()},
             'room': s.room.label,
             'assessors': render_template_string(_assessors, s=s, t=talk, url=url, text=text),
             'talks': render_template_string(_talks, s=s, url=url, text=text),
             'menu': render_template_string(_menu, old_slot=old_slot, new_slot=s, talk=talk, back_url=url, back_text=text)} for s in slots]

    return jsonify(data)
