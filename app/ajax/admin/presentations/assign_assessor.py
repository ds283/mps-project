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
        <span class="small text-success"><i class="fas fa-check-circle"></i> Pool overlap</span>
    {% else %}
        <span class="small text-danger"><i class="fas fa-times-circle"></i> No pool overlap</span>
    {% endif %}
    {% if slot.assessor_makes_valid(a.faculty_id) %}
        <span class="small text-success"><i class="fas fa-check-circle"></i> Makes valid</span>
    {% endif %}
    {% set rec = slot.owner %}
    {% set count = rec.get_number_faculty_slots(a.faculty_id) %}
    {% set pl = 's' %}{% if count == 1 %}{% set pl = '' %}{% endif %}
    <span class="small text-primary"><span class="fw-semibold">{{ count }}</span> session{{ pl }}</span>
</div>
"""


# language=jinja2
_sessions = """
<div class="d-flex flex-column justify-content-start align-items-start gap-3">
    {% for slot in slots %}
        <div class="bg-light p-2 w-100">
            <div class="d-flex flex-column justify-content-start align-items-start gap-1">
                <div class="d-flex flex-row flex-wrap justify-content-start align-items-center gap-2">
                    <span class="fw-semibold">{{ slot.session.label_as_string }}</span>
                    {{ simple_label(slot.room.label) }}
                    {% if slot.has_issues %}
                        {% set errors = slot.errors %}
                        {% set warnings = slot.warnings %}
                        <i class="fas fa-exclamation-triangle text-danger"></i>
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
                    {% endif %}
                    <div class="dropdown">
                        <a class="badge text-decoration-none text-nohover-light bg-secondary" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                            {{ slot.session.label_as_string }}
                        </a>
                        <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.schedule_adjust_assessors', id=slot.id, url=url, text=text) }}">
                                Reassign assessors...
                            </a>
                        </div>
                    </div>
                </div>
                <div class="d-flex flex-row flex-wrap justify-content-start align-items-start gap-2">
                    {% for talk in slot.talks %}
                        {% set style = talk.pclass.make_CSS_style() %}
                        <div>
                            <div class="dropdown">
                                <a class="badge text-decoration-none text-nohover-light {% if style %}bg-secondary{% else %}bg-info{% endif %}" {% if style %}style="{{ style }}"{% endif %} data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                                    {{ talk.owner.student.user.last_name }}
                                    ({{ talk.project.owner.user.last_name }} &ndash; {{ truncate(talk.project.name) }})
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
                        </div>
                    {% endfor %}
                </div>
                {% if slot.has_issues %}
                    {% set errors = slot.errors %}
                    {% set warnings = slot.warnings %}
                    <div class="d-flex flex-column justify-content-start align-items-start">
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
        <span class="text text-secondary"><i class="fas fa-times-circle"></i> No assignment</span>
    {% endfor %}
</div>
"""


# language=jinja2
_menu = """
<div class="float-end">
    <a href="{{ url_for('admin.schedule_attach_assessor', slot_id=slot.id, fac_id=a.faculty_id) }}" class="btn btn-outline-secondary btn-sm"><i class="fas fa-plus"></i> Attach</a>
</div>
"""


def assign_assessor_data(assessors, slot, url=None, text=None):
    simple_label = get_template_attribute("labels.html", "simple_label")
    truncate = get_template_attribute("macros.html", "truncate")

    data = [
        {
            "name": {"display": render_template_string(_name, a=a, slot=slot), "sortstring": a.faculty.user.last_name + a.faculty.user.first_name},
            "sessions": {
                "display": render_template_string(_sessions, a=a, slots=slots, url=url, text=text, simple_label=simple_label, truncate=truncate),
                "sortvalue": score,
            },
            "menu": render_template_string(_menu, a=a, slot=slot),
        }
        for a, slots, score in assessors
    ]

    return jsonify(data)
