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
    <span class="label label-primary">Finished</span>
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
<span class="label label-default">Levelling {{ m.levelling_bias }}</span>
<span class="label label-default">Group {{ m.intra_group_tension }}</span>
<span class="label label-default">Programme {{ m.programme_bias }}</span>
{% if not m.ignore_programme_prefs %}
    <p></p>
    {% set outcome = m.prefer_programme_status %}
    {% if outcome is not none %}
        {% set match, fail = outcome %}
        <span class="label label-success">Matched {{ match }} programme prefs</span>
        <span class="label {% if fail > 0 %}label-warning{% else %}label-success{% endif %}">Failed {{ fail }} programme prefs</span>
    {% endif %}
{% endif %}
<p></p>
{% set errors = m.errors %}
{% set warnings = m.warnings %}
{% if errors|length == 1 %}
    <span class="label label-danger">1 error</span>
{% elif errors|length > 1 %}
    <span class="label label-danger">{{ errors|length }} errors</span>
{% else %}
    <span class="label label-success">0 errors</span>
{% endif %}
{% if warnings|length == 1 %}
    <span class="label label-warning">1 warning</span>
{% elif warnings|length > 1 %}
    <span class="label label-warning">{{ warnings|length }} warnings</span>
{% else %}
    <span class="label label-success">0 warnings</span>
{% endif %}
{% if errors|length > 0 %}
    <div class="has-error">
        {% for item in errors %}
            {% if loop.index <= 10 %}
                <p class="help-block">{{ item }}</p>
            {% elif loop.index == 11 %}
                <p class="help-block">...</p>
            {% endif %}            
        {% endfor %}
    </div>
{% endif %}
{% if warnings|length > 0 %}
    <div class="has-error">
        {% for item in warnings %}
            {% if loop.index <= 10 %}
                <p class="help-block">{{ item }}</p>
            {% elif loop.index == 11 %}
                <p class="help-block">...</p>
            {% endif %}
        {% endfor %}
    </div>
{% endif %}
"""


_score = \
"""
{% if m.outcome == m.OUTCOME_OPTIMAL %}
    <span class="label label-success">{{ m.score }} original</span>
    {% if m.current_score %}
        <span class="label label-primary">{{ m.current_score|round(precision=2) }} current</span>
    {% else %}
        <span class="label label-warning">Current score undefined</span>
    {% endif %}
    <span class="label label-info">&delta; max {{ m.delta_max }}</span>
    <span class="label label-info">&delta; min {{ m.delta_min }}</span>
    <span class="label label-primary">CATS max {{ m.CATS_max }}</span>
    <span class="label label-primary">CATS min {{ m.CATS_min }}</span>
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
    
        {% if m.finished and m.outcome == m.OUTCOME_OPTIMAL %}
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
    {% if m.finished and m.outcome == m.OUTCOME_OPTIMAL %}
        <a href="{{ url_for('admin.match_student_view', id=m.id) }}">{{ m.name }}</a>
        {% if not m.is_valid %}
            <i class="fa fa-exclamation-triangle" style="color:red;"></i>
        {% endif %}
    {% else %}
        {{ m.name }}
    {% endif %}
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
