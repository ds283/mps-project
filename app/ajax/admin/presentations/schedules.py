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
    <span class="badge badge-primary">Finished</span>
    {% if s.solution_usable %}
        <span class="badge badge-success">Optimal solution</span>
    {% elif s.outcome == s.OUTCOME_NOT_SOLVED %}
        <span class="badge badge-warning">Not solved</span>
    {% elif s.outcome == s.OUTCOME_INFEASIBLE %}
        <span class="badge badge-danger">Infeasible</span>
    {% elif s.outcome == s.OUTCOME_UNBOUNDED %}
        <span class="badge badge-danger">Unbounded</span>
    {% elif s.outcome == s.OUTCOME_UNDEFINED %}
        <span class="badge badge-danger">Undefined</span>
    {% else %}
        <span class="badge badge-danger">Unknown outcome</span>
    {% endif %}
    <p></p>
    {% if s.solution_usable %}
        {% if s.draft_to_submitters is not none %}
            <span class="badge badge-info">Draft to submitters: {{ s.draft_to_submitters.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
        {% if s.draft_to_assessors is not none %}
            <span class="badge badge-info">Draft to assessors: {{ s.draft_to_assessors.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
        {% if s.final_to_submitters is not none %}
            <span class="badge badge-primary">Final to submitters: {{ s.final_to_submitters.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
        {% if s.final_to_assessors is not none %}
            <span class="badge badge-primary">Final to assessors: {{ s.final_to_assessors.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
    {% endif %}
    <p></p>
    {% if s.published and current_user.has_role('root') %}
        <span class="badge badge-primary"><i class="fas fa-check"></i> Published</span>
        (<a href="{{ url_for('admin.view_schedule', tag=s.tag) }}">public link</a>)
    {% endif %}
    {% if s.deployed and current_user.has_role('root') %}
        <span class="badge badge-success"><i class="fas fa-check"></i> Deployed</span>
        (<a href="{{ url_for('admin.view_schedule', tag=s.tag) }}">public link</a>)
    {% endif %}
{% else %}
    {% if s.awaiting_upload %}
        <span class="badge badge-success">Awaiting upload</span>
        {% if s.lp_file is not none %}
            <a href="{{ url_for('admin.download_generated_asset', asset_id=s.lp_file.id) }}">LP</a>
        {% endif %}
        {% if s.mps_file is not none %}
            <a href="{{ url_for('admin.download_generated_asset', asset_id=s.mps_file.id) }}">MPS</a>
        {% endif %}
    {% else %}
        <span class="badge badge-success">In progress</span>
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
    <span class="badge badge-secondary">Unknown</span>
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
    <span class="badge badge-success">Score {{ s.score }}</span>
{% else %}
    <span class="badge badge-secondary">Invalid</span>
{% endif %}
"""


_name = \
"""
<div>
    {% if s.finished and s.solution_usable %}
        <a href="{{ url_for('admin.schedule_view_sessions', id=s.id, text=text, url=url) }}">{{ s.name }}</a>
        <span class="badge badge-secondary">{{ s.tag }}</span>
        {% if not s.is_valid %}
            <i class="fas fa-exclamation-triangle" style="color:red;"></i>
        {% endif %}
    {% else %}
        {{ s.name }}
        <span class="badge badge-secondary">{{ s.tag }}</span>
    {% endif %}
</div>
{% if s.finished and s.solution_usable %}
    <p></p>
    {% if s.construct_time %}
        <span class="badge badge-secondary"><i class="fas fa-stopwatch"></i> Construct {{ s.formatted_construct_time }}</span>
    {% endif %}
    {% if s.compute_time %}
        <span class="badge badge-secondary"><i class="fas fa-stopwatch"></i> Compute {{ s.formatted_compute_time }}</span>
    {% endif %}
{% endif %}
"""


_info = \
"""
<span class="badge badge-info">Max assignment {{ s.assessor_assigned_limit }}</span>
<span class="badge badge-info">If needed cost {{ s.if_needed_cost }}</span>
<span class="badge badge-info">Levelling tension {{ s.levelling_tension }}</span>
{% if s.all_assessors_in_pool %}
    <span class="badge badge-info">All assessors in pool</span>
{% else %}
    <span class="badge badge-secondary">At least 1 assessor in pool</span>
{% endif %}
{% if s.finished and s.solution_usable %}
    <p></p>
    {% set value = s.number_slots %}{% set pl = 's' %}{% if value == 1 %}{% set pl = '' %}{% endif %}
    <span class="badge badge-primary">Uses {{ value }} slot{{ pl }}</span>
    {% set value = s.number_sessions %}{% set pl = 's' %}{% if value == 1 %}{% set pl = '' %}{% endif %}
    <span class="badge badge-primary">Uses {{ value }} session{{ pl }}</span>
    {% set value = s.number_rooms %}{% set pl = 's' %}{% if value == 1 %}{% set pl = '' %}{% endif %}
    <span class="badge badge-primary">Uses {{ value }} room{{ pl }}</span>
    {% set value = s.number_buildings %}{% set pl = 's' %}{% if value == 1 %}{% set pl = '' %}{% endif %}
    <span class="badge badge-primary">Uses {{ value }} building{{ pl }}</span>
    {% set value = s.number_ifneeded %}
    {% if value == 0 %}
        <span class="badge badge-success">Uses 0 if-needed</span>
    {% else %}
        <span class="badge badge-warning">Uses {{ value }} if-needed</span>
    {% endif %}
{% endif %}
<p><p>
<span class="badge badge-success">Solver {{ s.solver_name }}</span>
{% if not s.is_valid %}
    <p></p>
    {% set errors = s.errors %}
    {% set warnings = s.warnings %}
    {% if errors|length == 1 %}
        <span class="badge badge-danger">1 error</span>
    {% elif errors|length > 1 %}
        <span class="badge badge-danger">{{ errors|length }} errors</span>
    {% else %}
        <span class="badge badge-success">0 errors</span>
    {% endif %}
    {% if warnings|length == 1 %}
        <span class="badge badge-warning">1 warning</span>
    {% elif warnings|length > 1 %}
        <span class="badge badge-warning">{{ warnings|length }} warnings</span>
    {% else %}
        <span class="badge badge-success">0 warnings</span>
    {% endif %}
    {% if errors|length > 0 %}
        <div class="error-block">
            {% for item in errors %}
                {% if loop.index <= 10 %}
                    <p class="error-message">{{ item }}</p>
                {% elif loop.index == 11 %}
                    <p class="error-message">...</p>
                {% endif %}            
            {% endfor %}
        </div>
    {% endif %}
    {% if warnings|length > 0 %}
        <div class="error-block">
            {% for item in warnings %}
                {% if loop.index <= 10 %}
                    <p class="error-message">Warning: {{ item }}</p>
                {% elif loop.index == 11 %}
                    <p class="error-message">...</p>
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
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button"
            data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        {% if s.finished and s.solution_usable %}
            <a class="dropdown-item" href="{{ url_for('admin.schedule_view_sessions', id=s.id, text=text, url=url) }}">
                <i class="fas fa-search fa-fw"></i> Inspect schedule...
            </a>
            <div role="separator" class="dropdown-divider"></div>
        {% endif %}    

        {% if not s.finished %}
            {% set disabled = not current_user.has_role('root') %}
            {% if s.awaiting_upload %}
                <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.upload_schedule', schedule_id=s.id) }}"{% endif %}>
                    <i class="fas fa-cloud-upload fa-fw"></i> Upload solution...
                </a>
                <div role="separator" class="dropdown-divider"></div>
            {% endif %}
            <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.duplicate_schedule', id=s.id) }}"{% endif %}>
                <i class="fas fa-clone fa-fw"></i> Duplicate
            </a>
            <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.terminate_schedule', id=s.id) }}"{% endif %}>
                <i class="fas fa-hand-paper fa-fw"></i> Terminate
            </a>
        {% else %}
            {% if s.solution_usable %}
                <a class="dropdown-item" href="{{ url_for('admin.rename_schedule', id=s.id, url=url) }}">
                    <i class="fas fa-pencil-alt fa-fw"></i> Rename...
                </a>
                {% if s.is_modified %}
                    <a class="dropdown-item" href="{{ url_for('admin.revert_schedule', id=s.id) }}">
                        <i class="fas fa-undo fa-fw"></i> Revert to original
                    </a>
                {% endif %}
                <a class="dropdown-item" href="{{ url_for('admin.duplicate_schedule', id=s.id) }}">
                    <i class="fas fa-clone fa-fw"></i> Duplicate
                </a>
                <a class="dropdown-item" href="{{ url_for('admin.compare_schedule', id=s.id, url=url, text=text) }}">
                    <i class="fas fa-balance-scale fa-fw"></i> Compare to...
                </a>
                {% set disabled = valid %}
                <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.adjust_assessment_schedule', id=s.id) }}"{% endif %}>
                    <i class="fas fa-wrench fa-fw"></i> Impose constraints...
                </a>
            {% else %}
                <a class="dropdown-item disabled"><i class="fas fa-times fa-fw"></i> Solution is not usable</a>
            {% endif %}

            {% if current_user.has_role('root') or current_user.id == s.creator_id %}
                <a class="dropdown-item" href="{{ url_for('admin.delete_schedule', id=s.id) }}">
                    <i class="fas fa-trash fa-fw"></i> Delete
                </a>
            {% else %}
                <a class="dropdown-item disabled"><i class="fas fa-trash"></i> Delete</a>
            {% endif %}

            {% if current_user.has_role('root') %}
                <div role="separator" class="dropdown-divider"></div>
                <div class="dropdown-header">Superuser functions</div>

                {% if s.published %}
                    <a class="dropdown-item" href="{{ url_for('admin.unpublish_schedule', id=s.id) }}">
                        <i class="fas fa-eject fa-fw"></i> Unpublish
                    </a>
                {% else %}
                    {% if not s.deployed %}
                        <a class="dropdown-item" href="{{ url_for('admin.publish_schedule', id=s.id) }}">
                            <i class="fas fa-share-square fa-fw"></i> Publish to convenors
                        </a>
                    {% else %}
                        <a class="dropdown-item disabled"><i class="fas fa-ban"></i> Can't publish</a>
                    {% endif %}
                {% endif %}
                
                {% if s.deployed %}
                    {% if s.is_revokable %}
                        <a class="dropdown-item" href="{{ url_for('admin.undeploy_schedule', id=s.id) }}">
                            <i class="fas fa-eject fa-fw"></i> Revoke deployment
                        </a>
                    {% else %}
                        <a class="dropdown-item disabled"><i class="fas fa-ban fa-fw"></i> Can't revoke</a>
                    {% endif %}
                {% else %}
                    {% if s.owner.is_deployed %}
                        <a class="dropdown-item disabled"><i class="fas fa-ban fa-fw"></i> Can't deploy</a>
                    {% else %}
                        <a class="dropdown-item" href="{{ url_for('admin.deploy_schedule', id=s.id) }}">
                            <i class="fas fa-play fa-fw"></i> Deploy
                        </a>
                    {% endif %}
                {% endif %}
                
                {% if s.published or s.deployed %}
                    <div role="separator" class="dropdown-divider"></div>
                    <a class="dropdown-item" href="{{ url_for('admin.publish_schedule_submitters', id=s.id) }}">
                        <i class="fas fa-mail-bulk fa-fw"></i> Email to submitters
                    </a>
                    <a class="dropdown-item" href="{{ url_for('admin.publish_schedule_assessors', id=s.id) }}">
                        <i class="fas fa-mail-bulk fa-fw"></i> Email to assessors
                    </a>
                {% endif %}
            {% endif %}            
        {% endif %}        
    </div>
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
        <span class="badge badge-info">{{ num }} project{{ pl }}</span>
    </div>
{% endfor %}
{% set total = a.number_talks %}
{% set missing = a.number_not_attending %}
{% if total > 0 or missing > 0 %}
    <p></p>
    {% set pl = 's' %}{% if total == 1 %}{% set p = '' %}{% endif %}
    <span class="badge badge-primary">{{ total }} presentation{{ pl }}</span>
    {% if missing > 0 %}
        <span class="badge badge-warning">{{ missing }} not attending</span>
    {% else %}
        <span class="badge badge-success">{{ missing }} not attending</span>
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
