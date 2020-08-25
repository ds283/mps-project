#
# Created by David Seery on 2018-12-11.
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
<a href="mailto:{{ a.faculty.user.email }}">{{ a.faculty.user.name }}</a>
<div>
    {% if a.confirmed %}
        <span class="badge badge-success">Confirmed</span>
    {% else %}
        <span class="badge badge-danger">Not confirmed</span>
    {% endif %}
    {% if a.assigned_limit is not none %}
        <span class="badge badge-primary">Assignment limit {{ a.assigned_limit }}</span>
    {% endif %}
    {% if a.comment is not none and a.comment|length > 0 %}
        <span class="badge badge-info" data-toggle="tooltip" title="{{ a.comment }}">Comment</button>
    {% endif %}
</div>
"""


_sessions = \
"""
{% for slot in slots %}
    <div style="display: inline-block; margin-bottom:2px; margin-right:2px;">
        <div class="dropdown schedule-assign-button" style="display: inline-block;">
            {% set style = slot.session.get_label_type() %}
            <a class="badge {% if style is not none %}{{ style }}{% else %}badge-secondary{% endif %} dropdown-toggle" data-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                {{ slot.session.short_date_as_string }} {{ slot.session.session_type_string }}
            </a>
            <div class="dropdown-menu">
                <a class="dropdown-item" href="{{ url_for('admin.schedule_adjust_assessors', id=slot.id, url=url_for('admin.schedule_view_faculty', id=rec.id, url=back_url, text=back_text), text='schedule inspector faculty view') }}">
                    Reassign assessors...
                </a>
            </div>
        </div>
        {{ slot.room.label|safe }}
        {% if not slot.is_valid %}
            <i class="fas fa-exclamation-triangle" style="color:red;"></i>
        {% endif %}
        &emsp;
        {% for talk in slot.talks %}
            <div class="dropdown schedule-assign-button" style="display: inline-block;">
                {% set style = talk.pclass.make_CSS_style() %}
                <a class="badge {% if style %}badge-secondary{% else %}badge-info{% endif %} dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} data-toggle="dropdown" role="button" href="" aria-haspopup="true" aria-expanded="false">
                    {{ talk.owner.student.user.name }}
                </a>
                <div class="dropdown-menu">
                    <a class="dropdown-item" href="{{ url_for('admin.schedule_adjust_submitter', slot_id=slot.id, talk_id=talk.id, url=url_for('admin.schedule_view_faculty', id=rec.id, url=back_url, text=back_text), text='schedule inspector faculty view') }}">
                        Reassign presentation...
                    </a>
                </div>
            </div>
            {% if slot.session.submitter_unavailable(talk.id) %}
                <i class="fas fa-exclamation-triangle" style="color:red;"></i>
            {% endif %}
        {% endfor %}
    </div>
{% else %}
    <span class="badge badge-secondary">No assignment</span>
{% endfor %}
"""


_availability = \
"""
<span class="badge badge-success">{{ a.number_available }}</span>
<span class="badge badge-warning">{{ a.number_ifneeded }}</span>
<span class="badge badge-danger">{{ a.number_unavailable }}</span>
"""



def schedule_view_faculty(assessors, record, url=None, text=None):
    data = [{'name': {'display': render_template_string(_name, a=a),
                      'sortstring': a.faculty.user.last_name + a.faculty.user.first_name},
             'sessions': {'display': render_template_string(_sessions, a=a, slots=slots, rec=record, back_url=url, back_text=text),
                          'sortvalue': len(slots)},
             'availability': render_template_string(_availability, a=a)} for a, slots in assessors]

    return jsonify(data)
