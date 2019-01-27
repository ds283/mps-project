#
# Created by David Seery on 2018-12-18.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, render_template_string


_source = \
"""
{% macro slot_id(slot) %}
    {{ slot.session.label|safe }}
    {{ slot.room.label|safe }} 
    {{ slot.pclass.make_label()|safe }}
{% endmacro %}
{% macro show_changes(s, t) %}
    {% for assessor in s.assessors: %}
        {% if assessor not in t.assessors: %}
            <span class="label label-danger"><i class="fa fa-minus"></i> Assessor: {{ assessor.user.name }}</span>
        {% endif %}
    {% endfor %}
    {% for talk in s.talks %}
        {% if talk not in t.talks %}
            <span class="label label-danger"><i class="fa fa-minus"></i> Presenter: {{ talk.owner.student.user.name }}</span>
        {% endif %}
    {% endfor %}
{% endmacro %}
{% if op == 'move' %}
    <div>
        <span class="label label-warning">MOVE FROM</span>
        {{ slot_id(s) }}
    </div>
    {{ show_changes(s, t) }}
{% elif op == 'edit' %}
    <div>
        <span class="label label-primary">CHANGE FROM</span>
        {{ slot_id(s) }}
    </div>
    {{ show_changes(s, t) }}
{% elif op == 'add' %}
    <span class="label label-default">No counterpart</span>
{% elif op == 'delete' %}
    <div>
        <span class="label label-danger">DELETE</span>
        {{ slot_id(s) }}
    </div>  
    {% for assessor in s.assessors %}
        <span class="label label-danger"><i class="fa fa-minus"></i> Assessor: {{ assessor.user.name }}</span>
    {% endfor %}
    {% for talk in s.talks %}
        <span class="label label-danger"><i class="fa fa-minus"></i> Presenter: {{ talk.owner.student.user.name }}</span>
    {% endfor %}
{% else %}
    <span class="label label-danger">UNKNOWN DIFF OPERATION</span>
{% endif %}
"""


_target = \
"""
{% macro slot_id(slot) %}
    {{ slot.session.label|safe }}
    {{ slot.room.label|safe }}
    {{ slot.pclass.make_label()|safe }}
{% endmacro %}
{% macro show_changes(s, t) %}
    {% for assessor in t.assessors: %}
        {% if assessor not in s.assessors: %}
            <span class="label label-success"><i class="fa fa-plus"></i> Assessor: {{ assessor.user.name }}</span>
        {% endif %}
    {% endfor %}
    {% for talk in t.talks %}
        {% if talk not in s.talks %}
            <span class="label label-success"><i class="fa fa-plus"></i> Presenter: {{ talk.owner.student.user.name }}</span>
        {% endif %}
    {% endfor %}
{% endmacro %}
{% if op == 'move' %}
    <div>
        <span class="label label-warning">MOVE TO</span>
        {{ slot_id(t) }}
    </div>
    {{ show_changes(s, t) }}
{% elif op == 'edit' %}
    <div>
        <span class="label label-primary">CHANGE TO</span>
    </div>
    {{ show_changes(s, t) }}
{% elif op == 'add' %}
    <div>
        <span class="label label-success">ADD</span>
        {{ slot_id(t) }}
    </div>
    {% for assessor in t.assessors %}
        <span class="label label-success"><i class="fa fa-plus"></i> Assessor: {{ assessor.user.name }}</span>
    {% endfor %}
    {% for talk in t.talks %}
        <span class="label label-success"><i class="fa fa-plus"></i> Presenter: {{ talk.owner.student.user.name }}</span>
    {% endfor %}
{% elif op == 'delete' %}
    <span class="label label-default">No counterpart</span>
{% else %}
    <span class="label label-danger">UNKNOWN DIFF OPERATION</span>
{% endif %}
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button"
            data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('admin.merge_change_schedule', source_id=t.id if t is not none else -1, target_id=s.id if s is not none else -1, source_sched=tid, target_sched=sid) }}">
                <i class="fa fa-chevron-circle-left"></i> Apply change to source
            </a>
        </li>
        <li>
            <a href="{{ url_for('admin.merge_change_schedule', source_id=s.id if s is not none else -1, target_id=t.id if t is not none else -1, source_sched=sid, target_sched=tid) }}">
                <i class="fa fa-chevron-circle-right"></i> Revert change in target
            </a>
        </li>
    </ul>
</div>
"""


def compare_schedule_data(pairs, source_id, target_id):
    data = [{'source': {'display': render_template_string(_source, op=op, s=s, t=t),
                        'sortvalue': op},
             'target': {'display': render_template_string(_target, op=op, s=s, t=t),
                        'sortvalue': op},
             'menu': render_template_string(_menu, op=op, s=s, t=t, sid=source_id, tid=target_id)} for op, s, t in pairs]

    return jsonify(data)
