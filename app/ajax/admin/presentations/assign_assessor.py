#
# Created by David Seery on 2018-12-12.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, get_template_attribute

# language=jinja2
_name = """
<a class="text-decoration-none" href="mailto:{{ a.faculty.user.email }}">{{ a.faculty.user.name }}</a>
<div>
    {% if a.confirmed %}
        <span class="small text-success"><i class="fas fa-check-circle"></i> Confirmed</span>
    {% else %}
        <span class="small text-danger"><i class="fas fa-times-circle"></i> Not confirmed</span>
    {% endif %}
    {% if slot.session.faculty_ifneeded(a.faculty_id) %}
        <span class="small text-secondary">If needed</span>
    {% endif %}
</div>
<div class="d-flex flex-column gap-1 justify-content-start align-items-start">
    {% if slot.assessor_has_overlap(a.faculty_id) %}
        <span class="small text-success"><i class="fas fa-check"></i> Pool overlap</span>
    {% else %}
        <span class="small text-danger"><i class="fas fa-times"></i> No pool overlap</span>
    {% endif %}
    {% if slot.assessor_makes_valid(a.faculty_id) %}
        <span class="small text-success"><i class="fas fa-check"></i> Makes valid</span>
    {% endif %}
    {% set rec = slot.owner %}
    {% set count = rec.get_number_faculty_slots(a.faculty_id) %}
    {% set pl = 's' %}{% if count == 1 %}{% set pl = '' %}{% endif %}
    <span class="small text-primary"><span class="fw-semibold">{{ count }}</span> session{{ pl }}</span>
</div>
"""


# language=jinja2
_sessions = """
{% macro truncate_name(name, maxlength=25) %}
    {%- if name|length > maxlength -%}
        {{ name[0:maxlength] }}...
    {%- else -%}
        {{ name }}
    {%- endif -%}
{% endmacro %}
{% for slot in slots %}
    <div class="row vertical-top" style="margin-bottom: 3px;">
        <div class="col-3">
            <div class="dropdown schedule-assign-button" style="display: inline-block;">
                <a class="badge text-decoration-none text-nohover-light bg-secondary" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                    {{ slot.session.short_date_as_string }} {{ slot.session.session_type_string }}
                </a>
                <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.schedule_adjust_assessors', id=slot.id, url=url, text=text) }}">
                        Reassign assessors...
                    </a>
                </div>
            </div>
            {{ simple_label(slot.room.label) }}
            {% if slot.has_issues %}
                {% set errors = slot.errors %}
                {% set warnings = slot.warnings %}
                <i class="fas fa-exclamation-triangle text-danger"></i>
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
                </div>
            {% endif %}
        </div>
        <div class="col-9">
            {% for talk in slot.talks %}
                {% set style = talk.pclass.make_CSS_style() %}
                <div class="dropdown schedule-assign-button" style="display: inline-block;">
                    <a class="badge text-decoration-none text-nohover-light {% if style %}bg-secondary{% else %}bg-info{% endif %}" {% if style %}style="{{ style }}"{% endif %} data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                        {{ talk.owner.student.user.last_name }}
                        ({{ talk.project.owner.user.last_name }} &ndash; {{ truncate_name(talk.project.name) }})
                    </a>
                    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.schedule_adjust_submitter', slot_id=slot.id, talk_id=talk.id, url=url, text=text) }}">
                            Reassign assessors...
                        </a>
                    </div>
                </div>
                {% if slot.session.submitter_unavailable(talk.id) %}
                    <i class="fas fa-exclamation-triangle text-danger"></i>
                {% endif %}
            {% endfor %}
            {% if slot.has_issues %}
                {% set errors = slot.errors %}
                {% set warnings = slot.warnings %}
                <div class="mt-1">
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
        </div>
    </div>
{% else %}
    <span class="badge bg-secondary">No assignment</span>
{% endfor %}
"""


# language=jinja2
_menu = """
<div class="float-end">
    <a href="{{ url_for('admin.schedule_attach_assessor', slot_id=slot.id, fac_id=a.faculty_id) }}" class="btn btn-outline-secondary btn-sm"><i class="fas fa-plus"></i> Attach</a>
</div>
"""


def assign_assessor_data(assessors, slot, url=None, text=None):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [
        {
            "name": {"display": render_template_string(_name, a=a, slot=slot), "sortstring": a.faculty.user.last_name + a.faculty.user.first_name},
            "sessions": {
                "display": render_template_string(_sessions, a=a, slots=slots, url=url, text=text, simple_label=simple_label),
                "sortvalue": len(slots),
            },
            "menu": render_template_string(_menu, a=a, slot=slot),
        }
        for a, slots in assessors
    ]

    return jsonify(data)
