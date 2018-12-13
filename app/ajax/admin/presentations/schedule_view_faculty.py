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
&emsp;
{% if a.confirmed %}
    <span class="label label-success">Confirmed</span>
{% else %}
    <span class="label label-danger">Not confirmed</span>
{% endif %}
"""


_sessions = \
"""
{% for slot in slots %}
    <div style="display: inline-block; margin-bottom:2px; margin-right:2px;">
        <div class="dropdown schedule-assign-button" style="display: inline-block;">
            {% set style = slot.session.get_label_type() %}
            <a class="label {% if style is not none %}{{ style }}{% else %}label-default{% endif %} dropdown-toggle" type="button" data-toggle="dropdown">
                {{ slot.session.short_date_as_string }} {{ slot.session.session_type_string }}
                <span class="caret"></span>
            </a>
            <ul class="dropdown-menu">
                <li>
                    <a href="{{ url_for('admin.schedule_adjust_assessors', id=slot.id, url=url_for('admin.schedule_view_faculty', id=rec.id, url=back_url, text=back_text), text='schedule inspector faculty view') }}">
                        Reassign assessors...
                    </a>
                </li>
            </ul>
        </div>
        {{ slot.room.label|safe }}
        {% if not slot.is_valid %}
            <i class="fa fa-exclamation-triangle" style="color:red;"></i>
        {% endif %}
        &emsp;
        {% for talk in slot.talks %}
            <div class="dropdown schedule-assign-button" style="display: inline-block;">
                {% set style = talk.pclass.make_CSS_style() %}
                <a class="label {% if style %}label-default{% else %}label-info{% endif %} dropdown-toggle" {% if style %}style="{{ style }}"{% endif %} type="button" data-toggle="dropdown">
                    {{ talk.owner.student.user.name }}
                    <span class="caret"></span>
                </a>
                <ul class="dropdown-menu">
                    <li>
                        <a href="{{ url_for('admin.schedule_adjust_submitter', slot_id=slot.id, talk_id=talk.id, url=url_for('admin.schedule_view_faculty', id=rec.id, url=back_url, text=back_text), text='schedule inspector faculty view') }}">
                            Reassign presentation...
                        </a>
                    </li>
                </ul>
            </div>
            {% if slot.session.submitter_unavailable(talk.id) %}
                <i class="fa fa-exclamation-triangle" style="color:red;"></i>
            {% endif %}
        {% endfor %}
    </div>
{% else %}
    <span class="label label-default">No assignment</span>
{% endfor %}
"""


_availability = \
"""
<span class="label label-success">{{ a.number_available }}</span>
<span class="label label-warning">{{ a.number_ifneeded }}</span>
<span class="label label-danger">{{ a.number_unavailable }}</span>
"""



def schedule_view_faculty(assessors, record, url=None, text=None):
    data = [{'name': {'display': render_template_string(_name, a=a),
                      'sortstring': a.faculty.user.last_name + a.faculty.user.first_name},
             'sessions': {'display': render_template_string(_sessions, a=a, slots=slots, rec=record, back_url=url, back_text=text),
                          'sortvalue': len(slots)},
             'availability': render_template_string(_availability, a=a)} for a, slots in assessors]

    return jsonify(data)