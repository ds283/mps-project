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
    {% if s.solution_usable %}
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
    {% if s.awaiting_upload %}
        <span class="label label-success">Awaiting upload</span>
    {% else %}
        <span class="label label-success">In progress</span>
    {% endif %}
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
{% if s.solution_usable %}
    <span class="label label-success">Score {{ s.score }}</span>
{% else %}
    <span class="label label-default">Invalid</span>
{% endif %}
"""


_name = \
"""
    {% if s.finished and s.solution_usable %}
        <a href="{{ url_for('admin.schedule_view_sessions', id=s.id, text=text, url=url) }}">{{ s.name }}</a>
        {% if not s.is_valid %}
            <i class="fa fa-exclamation-triangle" style="color:red;"></i>
        {% endif %}
    {% else %}
        {{ s.name }}
    {% endif %}
</div>
<p></p>
{% if s.finished and s.solution_usable %}
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
{% if s.deployed and current_user.has_role('root') %}
    <span class="label label-success"><i class="fa fa-check"></i> Deployed</span>
{% endif %}
"""


_info = \
"""
<span class="label label-info">Max group size {{ s.max_group_size }}</span>
<span class="label label-info">Max assessor assignment {{ s.assessor_assigned_limit }}</span>
<span class="label label-info">If needed cost {{ s.if_needed_cost }}</span>
<span class="label label-info">Levelling tension {{ s.levelling_tension }}</span>
{% if s.finished and s.solution_usable %}
    {% set value = s.number_sessions %}{% set pl = 's' %}{% if value == 1 %}{% set pl = '' %}{% endif %}
    <span class="label label-info">Uses {{ value }} session{{ pl }}</span>
    {% set value = s.number_rooms %}{% set pl = 's' %}{% if value == 1 %}{% set pl = '' %}{% endif %}
    <span class="label label-info">Uses {{ value }} room{{ pl }}</span>
    {% set value = s.number_buildings %}{% set pl = 's' %}{% if value == 1 %}{% set pl = '' %}{% endif %}
    <span class="label label-info">Uses {{ value }} building{{ pl }}</span>
{% endif %}
<p><p>
<span class="label label-success">Solver {{ s.solver_name }}</span>
{% if not s.is_valid %}
    <p></p>
    {% set errors = s.errors %}
    {% set warnings = s.warnings %}
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
                    <p class="help-block">Warning: {{ item }}</p>
                {% elif loop.index == 11 %}
                    <p class="help-block">...</p>
                {% endif %}
            {% endfor %}
        </div>
    {% endif %}
{% endif %}
"""

_menu = \
"""
{% set valid = s.is_valid %}
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button"
            data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        {% if s.finished and s.solution_usable %}
            <li>
                <a href="{{ url_for('admin.schedule_view_sessions', id=s.id, text=text, url=url) }}">
                    <i class="fa fa-search"></i> Inspect schedule
                </a>
            </li>
            <li role="separator" class="divider">
        {% endif %}    

        {% if not s.finished %}
            {% set disabled = not current_user.has_role('root') %}
            {% if s.awaiting_upload %}
                <li {% if disabled %}class="disabled"{% endif %}>
                    <a {% if not disabled %}href="{{ url_for('admin.upload_schedule', schedule_id=s.id) }}"{% endif %}>
                        <i class="fa fa-cloud-upload"></i> Upload solution...
                    </a>
                </li>
            {% endif %}
            <li {% if disabled %}class="disabled"{% endif %}>
                <a {% if not disabled %}href="{{ url_for('admin.terminate_schedule', id=s.id) }}"{% endif %}>
                    <i class="fa fa-hand-paper-o"></i> Terminate
                </a>
            </li>
        {% else %}
            {% if s.solution_usable %}
                <li>
                    <a href="{{ url_for('admin.rename_schedule', id=s.id, url=url) }}">
                        <i class="fa fa-exchange"></i> Rename
                    </a>
                </li>
                {% set disabled = valid %}
                <li {% if disabled %}class="disabled"{% endif %}>
                    <a {% if not disabled %}href="{{ url_for('admin.adjust_assessment_schedule', id=s.id) }}"{% endif %}>
                        <i class="fa fa-wrench"></i> Adjust to constraints
                    </a>
                </li>
            {% else %}
                <li class="disabled">
                    <a><i class="fa fa-exchange"></i> Rename</a>
                </li>
                <li class="disabled">
                    <a><i class="fa fa-wrench"></i> Adjust to constraints</a>
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
                    {% if not s.deployed %}
                        <li>
                            <a href="{{ url_for('admin.publish_schedule', id=s.id) }}">
                                <i class="fa fa-share"></i> Publish to convenors
                            </a>
                        </li>
                    {% else %}
                        <li class="disabled">
                            <a><i class="fa fa-share"></i> Can't publish</a>
                        </li>
                    {% endif %}
                {% endif %}
                
                {% if s.deployed and s.is_revokable %}
                    <li>
                        <a href="{{ url_for('admin.undeploy_schedule', id=s.id) }}">
                            <i class="fa fa-stop-circle"></i> Revoke deployment
                        </a>
                    </li>
                {% else %}
                    {% if s.owner.is_deployed %}
                        <li class="disabled">
                            <a><i class="fa fa-upload"></i> Can't deploy</a>
                        </li>
                    {% else %}
                        <li>
                            <a href="{{ url_for('admin.deploy_schedule', id=s.id) }}">
                                <i class="fa fa-upload"></i> Deploy
                            </a>
                        </li>
                    {% endif %}
                {% endif %}
            {% endif %}            
        {% endif %}        
    </ul>
</div>
"""


_periods = \
"""
{{ a.name }}
<p></p>
{% for period in a.submission_periods %}
    <div style="display: inline-block;">
        {{ period.label|safe }}
        {% set num = period.number_projects %}
        {% set pl = 's' %}
        {% if num == 1 %}{% set pl = '' %}{% endif %}
        <span class="label label-info">{{ num }} project{{ pl }}</span>
    </div>
{% endfor %}
{% set total = a.number_talks %}
{% set missing = a.number_not_attending %}
{% if total > 0 or missing > 0 %}
    <p></p>
    {% set pl = 's' %}{% if total == 1 %}{% set p = '' %}{% endif %}
    <span class="label label-primary">{{ total }} presentation{{ pl }}</span>
    {% if missing > 0 %}
        <span class="label label-warning">{{ missing }} not attending</span>
    {% else %}
        <span class="label label-success">{{ missing }} not attending</span>
    {% endif %}
{% endif %}
"""


def assessment_schedules_data(schedules, text, url):
    """
    Build AJAX JSON payload
    :param schedules: 
    :return: 
    """
    
    data = [{'name': render_template_string(_name, s=s, text=text, url=url),
             'status': render_template_string(_status, s=s),
             'score': {
                 'display': render_template_string(_score, s=s),
                 'value': float(s.score) if s.solution_usable and s.score is not None else 0
             },
             'timestamp': render_template_string(_timestamp, s=s),
             'info': render_template_string(_info, s=s),
             'periods': render_template_string(_periods, a=s.owner),
             'menu': render_template_string(_menu, s=s, text=text, url=url)} for s in schedules]

    return jsonify(data)
