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
    {% for assessor in assessors %}
        <span class="label label-danger"><i class="fa fa-minus"></i> Assessor: {{ assessor.user.name }}</span>
    {% endfor %}
    {% for talk in talks %}
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
    {% for assessor in assessors %}
        <span class="label label-success"><i class="fa fa-plus"></i> Assessor: {{ assessor.user.name }}</span>
    {% endfor %}
    {% for talk in talks %}
        <span class="label label-success"><i class="fa fa-plus"></i> Presenter: {{ talk.owner.student.user.name }}</span>
    {% endfor %}
{% elif op == 'delete' %}
    <span class="label label-default">No counterpart</span>
{% else %}
    <span class="label label-danger">UNKNOWN DIFF OPERATION</span>
{% endif %}
"""


def compare_schedule_data(pairs):
    data = [{'source': {'display': render_template_string(_source, op=op, s=s, t=t),
                        'sortvalue': op},
             'target': {'display': render_template_string(_target, op=op, s=s, t=t),
                        'sortvalue': op}} for op, s, t in pairs]

    return jsonify(data)
