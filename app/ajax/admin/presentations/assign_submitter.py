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
{% for assessor in s.assessors %}
    <div>
        <div class="dropdown schedule-assign-button" style="display: inline-block;">
            <a class="label label-default" type="button" data-toggle="dropdown">
                {{ assessor.user.name }}
                <span class="caret"></span>
            </a>
            <ul class="dropdown-menu">
                <li>
                    <a href="{{ url_for('admin.schedule_adjust_assessors', id=s.id, url=url, text=text) }}">
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
        <a class="label {% if style %}label-default{% else %}label-info{% endif %}" {% if style %}style="{{ style }}"{% endif %} type="button" data-toggle="dropdown">
            {{ talk.owner.student.user.name }}
            <span class="caret"></span>
        </a>
        <ul class="dropdown-menu">
            <li>
                <a href="{{ url_for('admin.schedule_adjust_submitter', slot_id=s.id, talk_id=talk.id, url=url, text=text) }}">
                    Reassign presentation...
                </a>
            </li>
        </ul>
    </div>
    {% if s.session.submitter_unavailable(talk.id) %}
        <i class="fa fa-exclamation-triangle" style="color:red;"></i>
    {% endif %}
{% endfor %}
"""


_menu = \
"""
<div class="pull-right">
    <a href="{{ url_for('admin.schedule_move_submitter', old_id=old_slot.id, new_id=new_slot.id, talk_id=talk.id, url=back_url, text=back_text) }}" class="btn btn-default btn-sm">
        <i class="fa fa-arrows"></i> Move
    </a>
</div>
"""


def assign_submitter_data(slots, old_slot, talk, url=None, text=None):
    data = [{'session': {'display': render_template_string(_name, s=s),
                         'sortvalue': s.session.date.isoformat()},
             'room': s.room.label,
             'assessors': render_template_string(_assessors, s=s, url=url, text=text),
             'talks': render_template_string(_talks, s=s, url=url, text=text),
             'menu': render_template_string(_menu, old_slot=old_slot, new_slot=s, talk=talk, back_url=url, back_text=text)} for s in slots]

    return jsonify(data)
