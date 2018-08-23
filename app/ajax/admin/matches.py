#
# Created by David Seery on 17/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, render_template_string


_status = \
"""
{% if m.finished %}
    <span class="label label-default">Finished</span>
    {% if m.outcome == m.OUTCOME_OPTIMAL %}
        <span class="label label-success">Optimal solution</span>
    {% elif m.outcome == m.OUTCOME_NOT_SOLVED %}
        <span class="label label-warning">Not solved</span>
    {% elif m.outcome == m.OUTCOME_INFEASIBLE %}
        <span class="label label-danger">Infeasible</span>
    {% elif m.outcome == m.OUTCOME_UNBOUNDED %}
        <span class="label label-danger">Unbounded</span>
    {% elif m.outcome == m.OUTCOME_UNDEFINED %}
        <span class="label label-danger">Undefined</span>
    {% else %}
        <span class="label label-danger">Unknown outcome</span>
    {% endif %}
{% else %}
    <span class="label label-success">In progress</span>
{% endif %}
    """


_owner = \
"""
<a href="mailto:{{ m.owner.email }}">{{ m.owner.name }}</a>
"""


_timestamp = \
"""
{{ m.timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
"""


_info = \
"""
<span class="label label-primary">Supervisor {{ m.supervising_limit }} CATS</span>
<span class="label label-info">2nd mark {{ m.marking_limit }} CATS</span>
{% if m.ignore_per_faculty_limits %}
    <span class="label label-warning">Ignore per-faculty limits</span>
{% else %}
    <span class="label label-default">Apply per-faculty limits</span>
{% endif %}
{% if m.ignore_programme_prefs %}
    <span class="label label-warning">Ignore programmes prefs/span>
{% else %}
    <span class="label label-default">Apply programme prefs</span>
{% endif %}
<span class="label label-info">Marker multiplicity {{ m.max_marking_multiplicity }}</span>
<span class="label label-info">Memory {{ m.years_memory }} yr</span>
"""


_score = \
"""
{% if m.outcome == m.OUTCOME_OPTIMAL %}
    <span class="label label-success">{{ m.score }}</span>
{% else %}
    <span class="label label-default">Invalid</span>
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
    
        {% if m.finished %}
            <li>
                <a href="{{ url_for('admin.match_student_view', id=m.id) }}">
                    Inspect match
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>Inspect match</a>
            </li>
        {% endif %}
    
        <li role="separator" class="divider">
        
        {% if not m.finished %}
            <li>
                <a href="{{ url_for('admin.terminate_match', id=m.id) }}">
                    <i class="fa fa-times"></i> Terminate
                </a>
            </li>
        {% else %}
            <li>
                <a href="{{ url_for('admin.delete_match', id=m.id) }}">
                    <i class="fa fa-trash"></i> Delete
                </a>
            </li>
        {% endif %}
    </ul>
</div>
"""


_name = \
"""
<div>
    <a href="{{ url_for('admin.match_student_view', id=m.id) }}">{{ m.name }}</a>
</div>
{% if m.finished and m.outcome == m.OUTCOME_OPTIMAL %}
    {% if m.construct_time %}
        <span class="label label-default">Construct {{ m.formatted_construct_time }}</span>
    {% endif %}
    {% if m.compute_time %}
        <span class="label label-default">Compute {{ m.formatted_compute_time }}</span>
    {% endif %}
{% endif %}
"""


def matches_data(matches):
    """
    Build AJAX JSON payload
    :param matches:
    :return:
    """

    data = [{'name': render_template_string(_name, m=m),
             'status': render_template_string(_status, m=m),
             'owner': render_template_string(_owner, m=m),
             'score': {
                 'display': render_template_string(_score, m=m),
                 'value': float(m.score) if m.outcome == m.OUTCOME_OPTIMAL and m.score is not None else 0
             },
             'timestamp': render_template_string(_timestamp, m=m),
             'info': render_template_string(_info, m=m),
             'menu': render_template_string(_menu, m=m)} for m in matches]

    return jsonify(data)
