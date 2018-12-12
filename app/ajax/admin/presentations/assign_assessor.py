#
# Created by David Seery on 2018-12-12.
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
        <span class="label label-success">Confirmed</span>
    {% else %}
        <span class="label label-danger">Not confirmed</span>
    {% endif %}
    {% if slot.session.faculty_ifneeded(a.faculty_id) %}
        <span class="label label-warning">If needed</span>
    {% endif %}
</div>
"""


_sessions = \
"""
{% for slot in slots %}
    <div style="display: inline-block; margin-bottom: 2px; margin-top: 2px;">
        {{ slot.session.label|safe }}
        {{ slot.room.label|safe }}
        {% if not slot.is_valid %}
            <i class="fa fa-exclamation-triangle" style="color:red;"></i>
        {% endif %}
        &emsp;
        {% for talk in slot.talks %}
            {% set style = talk.pclass.make_CSS_style() %}
            <span class="label {% if style %}label-default{% else %}label-info{% endif %}" {% if style %}style="{{ style }}"{% endif %}>{{ talk.owner.student.user.last_name }}</span>
            {% if slot.session.submitter_unavailable(talk.id) %}
                <i class="fa fa-exclamation-triangle" style="color:red;"></i>
            {% endif %}
        {% endfor %}
    </div>
{% else %}
    <span class="label label-default">No assignment</span>
{% endfor %}
"""


_menu = \
"""
<div class="pull-right">
    <a href="{{ url_for('admin.schedule_attach_assessor', slot_id=slot.id, fac_id=a.faculty_id) }}" class="btn btn-default btn-sm"><i class="fa fa-plus"></i> Attach</a>
</div>
"""


def assign_assessor_data(assessors, slot):
    data = [{'name': {'display': render_template_string(_name, a=a, slot=slot),
                      'sortstring': a.faculty.user.last_name + a.faculty.user.first_name},
             'sessions': {'display': render_template_string(_sessions, a=a, slots=slots),
                          'sortvalue': len(slots)},
             'menu': render_template_string(_menu, a=a, slot=slot)} for a, slots in assessors]

    return jsonify(data)
