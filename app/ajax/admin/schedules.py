#
# Created by David Seery on 2018-10-07.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_status = \
"""
{% if s.finished %}
    <span class="label label-primary">Finished</span>
    {% if s.outcome == s.OUTCOME_OPTIMAL %}
        <span class="label label-success">Optimal solution</span>
    {% elif s.outcome == s.OUTCOME_NOT_SOLVED %}
        <span class="label label-warning">Not solved</span>
    {% elif s.outcome == s.OUTCOME_INFEASIBLE %}
        <span class="label label-danger">Infeasible</span>
    {% elif s.outcome == s.OUTCOME_UNBOUNDED %}
        <span class="label label-danger">Unbounded</span>
    {% elif s.outcome == s.OUTCOME_UNDEFINED %}
        <span class="label label-danger">Undefined</span>
    {% else %}
        <span class="label label-danger">Unknown outcome</span>
    {% endif %}
    <p></p>
{% else %}
    <span class="label label-success">In progress</span>
{% endif %}
"""


_timestamp = \
"""
Created by
<a href="mailto:{{ s.created_by.email }}">{{ s.created_by.name }}</a>
on
{% if s.creation_timestamp is not none %}
    {{ s.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
{% else %}
    <span class="label label-default">Unknown</span>
{% endif %}
{% if s.last_edited_by is not none %}
    <p></p>
    Last edited by 
    <a href="mailto:{{ s.last_edited_by.email }}">{{ s.last_edited_by.name }}</a>
    {% if s.last_edit_timestamp is not none %}
        {{ s.last_edit_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
    {% endif %}
{% endif %}
"""


_score = \
"""
{% if s.outcome == s.OUTCOME_OPTIMAL %}
    <span class="label label-success">Score {{ s.score }}</span>
{% else %}
    <span class="label label-default">Invalid</span>
{% endif %}
"""


_name = \
"""
    {% if s.finished and s.outcome == s.OUTCOME_OPTIMAL %}
        <a href="{{ url_for('admin.schedule_view_sessions', id=s.id, text='assessment schedule manager', url=url_for('admin.assessment_schedules', id=s.owner.id)) }}">{{ s.name }}</a>
        {% if not s.is_valid %}
            <i class="fa fa-exclamation-triangle" style="color:red;"></i>
        {% endif %}
    {% else %}
        {{ s.name }}
    {% endif %}
</div>
<p></p>
{% if s.finished and s.outcome == s.OUTCOME_OPTIMAL %}
    <p></p>
    {% if s.construct_time %}
        <span class="label label-default"><i class="fa fa-clock-o"></i> Construct {{ s.formatted_construct_time }}</span>
    {% endif %}
    {% if s.compute_time %}
        <span class="label label-default"><i class="fa fa-clock-o"></i> Compute {{ s.formatted_compute_time }}</span>
    {% endif %}
{% endif %}
<p></p>
{% if s.published and current_user.has_role('root') %}
    <span class="label label-primary">Published</span>
{% endif %}
"""


_info = \
"""
<span class="label label-default">Max group size {{ s.max_group_size }}</span>
<p><p>
<span class="label label-success">Solver {{ s.solver_name }}</span>
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
        {% if s.finished and s.outcome == s.OUTCOME_OPTIMAL %}
            <li>
                <a href="{{ url_for('admin.schedule_view_sessions', id=s.id, text='assessment schedule manager', url=url_for('admin.assessment_schedules', id=s.owner.id)) }}">
                    <i class="fa fa-search"></i> Inspect schedule
                </a>
            </li>
            <li role="separator" class="divider">
        {% endif %}    

        {% if not s.finished %}
            <li>
                <a href="{{ url_for('admin.terminate_schedule', id=s.id) }}">
                    <i class="fa fa-times"></i> Terminate
                </a>
            </li>
        {% else %}
            {% if s.outcome == s.OUTCOME_OPTIMAL %}
                <li>
                    <a href="#">
                        <i class="fa fa-pencil"></i> Rename
                    </a>
                </li>
            {% else %}
                <li class="disabled">
                    <a><i class="fa fa-pencil"></i> Rename</a>
                </li>
            {% endif %}

            {% if current_user.has_role('root') or current_user.id == s.creator_id %}
                <li>
                    <a href="{{ url_for('admin.delete_schedule', id=s.id) }}">
                        <i class="fa fa-trash"></i> Delete
                    </a>
                </li>
            {% else %}
                <li class="disabled">
                    <a><i class="fa fa-trash"></i> Delete</a>
                </li>
            {% endif %}

            {% if current_user.has_role('root') %}
                <li role="separator" class="divider">
                <li class="dropdown-header">Superuser functions</li>

                {% if s.published %}
                    <li>
                        <a href="{{ url_for('admin.unpublish_schedule', id=s.id) }}">
                            <i class="fa fa-stop-circle"></i> Unpublish
                        </a>
                    </li>
                {% else %}
                    <li>
                        <a href="{{ url_for('admin.publish_schedule', id=s.id) }}">
                            <i class="fa fa-share"></i> Publish to convenors
                        </a>
                    </li>
                {% endif %}
            {% endif %}            
        {% endif %}        
    </ul>
</div>
"""


def assessment_schedules_data(schedules):
    """
    Build AJAX JSON payload
    :param schedules: 
    :return: 
    """
    
    data = [{'name': render_template_string(_name, s=s),
             'status': render_template_string(_status, s=s),
             'score': {
                 'display': render_template_string(_score, s=s),
                 'value': float(s.score) if s.outcome == s.OUTCOME_OPTIMAL and s.score is not None else 0
             },
             'timestamp': render_template_string(_timestamp, s=s),
             'info': render_template_string(_info, s=s),
             'menu': render_template_string(_menu, s=s)} for s in schedules]

    return jsonify(data)
