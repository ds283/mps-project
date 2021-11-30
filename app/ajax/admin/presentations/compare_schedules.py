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


# language=jinja2
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
            <span class="badge bg-danger"><i class="fas fa-minus"></i> Assessor: {{ assessor.user.name }}</span>
        {% endif %}
    {% endfor %}
    {% for talk in s.talks %}
        {% if talk not in t.talks %}
            <span class="badge bg-danger"><i class="fas fa-minus"></i> Presenter: {{ talk.owner.student.user.name }}</span>
        {% endif %}
    {% endfor %}
{% endmacro %}
{% if op == 'move' %}
    <div>
        <span class="badge bg-warning text-dark">MOVE FROM</span>
        {{ slot_id(s) }}
    </div>
    {{ show_changes(s, t) }}
{% elif op == 'edit' %}
    <div>
        <span class="badge bg-primary">CHANGE FROM</span>
        {{ slot_id(s) }}
    </div>
    {{ show_changes(s, t) }}
{% elif op == 'add' %}
    <span class="badge bg-secondary">No counterpart</span>
{% elif op == 'delete' %}
    <div>
        <span class="badge bg-danger">DELETE</span>
        {{ slot_id(s) }}
    </div>  
    {% for assessor in s.assessors %}
        <span class="badge bg-danger"><i class="fas fa-minus"></i> Assessor: {{ assessor.user.name }}</span>
    {% endfor %}
    {% for talk in s.talks %}
        <span class="badge bg-danger"><i class="fas fa-minus"></i> Presenter: {{ talk.owner.student.user.name }}</span>
    {% endfor %}
{% else %}
    <span class="badge bg-danger">UNKNOWN DIFF OPERATION</span>
{% endif %}
"""


# language=jinja2
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
            <span class="badge bg-success"><i class="fas fa-plus"></i> Assessor: {{ assessor.user.name }}</span>
        {% endif %}
    {% endfor %}
    {% for talk in t.talks %}
        {% if talk not in s.talks %}
            <span class="badge bg-success"><i class="fas fa-plus"></i> Presenter: {{ talk.owner.student.user.name }}</span>
        {% endif %}
    {% endfor %}
{% endmacro %}
{% if op == 'move' %}
    <div>
        <span class="badge bg-warning text-dark">MOVE TO</span>
        {{ slot_id(t) }}
    </div>
    {{ show_changes(s, t) }}
{% elif op == 'edit' %}
    <div>
        <span class="badge bg-primary">CHANGE TO</span>
    </div>
    {{ show_changes(s, t) }}
{% elif op == 'add' %}
    <div>
        <span class="badge bg-success">ADD</span>
        {{ slot_id(t) }}
    </div>
    {% for assessor in t.assessors %}
        <span class="badge bg-success"><i class="fas fa-plus"></i> Assessor: {{ assessor.user.name }}</span>
    {% endfor %}
    {% for talk in t.talks %}
        <span class="badge bg-success"><i class="fas fa-plus"></i> Presenter: {{ talk.owner.student.user.name }}</span>
    {% endfor %}
{% elif op == 'delete' %}
    <span class="badge bg-secondary">No counterpart</span>
{% else %}
    <span class="badge bg-danger">UNKNOWN DIFF OPERATION</span>
{% endif %}
"""


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.merge_change_schedule', source_id=t.id if t is not none else -1, target_id=s.id if s is not none else -1, source_sched=tid, target_sched=sid) }}">
            <i class="fas fa-chevron-circle-left fa-fw"></i> Apply change to source
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.merge_change_schedule', source_id=s.id if s is not none else -1, target_id=t.id if t is not none else -1, source_sched=sid, target_sched=tid) }}">
            <i class="fas fa-chevron-circle-right fa-fw"></i> Revert change in target
        </a>
    </div>
</div>
"""


def compare_schedule_data(pairs, source_id, target_id):
    data = [{'source': {'display': render_template_string(_source, op=op, s=s, t=t),
                        'sortvalue': op},
             'target': {'display': render_template_string(_target, op=op, s=s, t=t),
                        'sortvalue': op},
             'menu': render_template_string(_menu, op=op, s=s, t=t, sid=source_id, tid=target_id)} for op, s, t in pairs]

    return jsonify(data)
