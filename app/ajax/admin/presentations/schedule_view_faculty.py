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
        {{ slot.session.label|safe }}
        {{ slot.room.label|safe }}
        {% if not slot.is_valid %}
            <i class="fa fa-exclamation-triangle" style="color:red;"></i>
        {% endif %}
        &emsp;
        {% for talk in slot.talks %}
            {% set style = talk.pclass.make_CSS_style() %}
            <span class="label {% if style %}label-default{% else %}label-info{% endif %}" {% if style %}style="{{ style }}"{% endif %}>{{ talk.owner.student.user.name }}</span>
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



def schedule_view_faculty(assessors, record):
    data = [{'name': {'display': render_template_string(_name, a=a),
                      'sortstring': a.faculty.user.last_name + a.faculty.user.first_name},
             'sessions': {'display': render_template_string(_sessions, a=a, slots=slots),
                          'sortvalue': len(slots)},
             'availability': render_template_string(_availability, a=a)} for a, slots in assessors]

    return jsonify(data)
