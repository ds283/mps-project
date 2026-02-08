#
# Created by David Seery on 2018-12-11.
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
        <span class="badge bg-success">Confirmed</span>
    {% else %}
        <span class="badge bg-danger">Not confirmed</span>
    {% endif %}
    {% if a.assigned_limit is not none %}
        <span class="badge bg-primary">Assignment limit {{ a.assigned_limit }}</span>
    {% endif %}
    {% if a.comment is not none and a.comment|length > 0 %}
        <span class="badge bg-info" data-bs-toggle="tooltip" title="{{ a.comment }}">Comment</span>
    {% endif %}
</div>
"""


# language=jinja2
_sessions = """
{% for slot in slots %}
    <div style="display: inline-block; margin-bottom:2px; margin-right:2px;">
        <div class="dropdown schedule-assign-button" style="display: inline-block;">
            <a class="badge text-decoration-none text-nohover-light bg-secondary dropdown-toggle" data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                {{ slot.session.label_as_string }}
            </a>
            <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.schedule_adjust_assessors', id=slot.id, url=url_for('admin.schedule_view_faculty', id=rec.id, url=back_url, text=back_text), text='schedule inspector faculty view') }}">
                    Reassign assessors...
                </a>
            </div>
        </div>
        {{ simple_label(slot.room.label) }}
        {% if slot.has_issues %}
            <i class="fas fa-exclamation-triangle text-danger"></i>
        {% endif %}
        &emsp;
        {% for talk in slot.talks %}
            <div class="dropdown schedule-assign-button" style="display: inline-block;">
                {% set style = talk.pclass.make_CSS_style() %}
                <a class="badge text-decoration-none text-nohover-light {% if style %}bg-secondary{% else %}bg-info{% endif %} dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} data-bs-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                    {{ talk.owner.student.user.name }}
                </a>
                <div class="dropdown-menu dropdown-menu-dark mx-0 border-0">
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.schedule_adjust_submitter', slot_id=slot.id, talk_id=talk.id, url=url_for('admin.schedule_view_faculty', id=rec.id, url=back_url, text=back_text), text='schedule inspector faculty view') }}">
                        Reassign presentation...
                    </a>
                </div>
            </div>
            {% if slot.session.submitter_unavailable(talk.id) %}
                <i class="fas fa-exclamation-triangle text-danger"></i>
            {% endif %}
        {% endfor %}
    </div>
{% else %}
    <span class="badge bg-secondary">No assignment</span>
{% endfor %}
"""


# language=jinja2
_availability = """
<span class="badge bg-success">{{ a.number_available }}</span>
<span class="badge bg-warning text-dark">{{ a.number_ifneeded }}</span>
<span class="badge bg-danger">{{ a.number_unavailable }}</span>
"""


def schedule_view_faculty(assessors, record, url=None, text=None):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [
        {
            "name": {"display": render_template_string(_name, a=a), "sortstring": a.faculty.user.last_name + a.faculty.user.first_name},
            "sessions": {
                "display": render_template_string(_sessions, a=a, slots=slots, rec=record, back_url=url, back_text=text, simple_label=simple_label),
                "sortvalue": len(slots),
            },
            "availability": render_template_string(_availability, a=a),
        }
        for a, slots in assessors
    ]

    return jsonify(data)
