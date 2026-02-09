#
# Created by David Seery on 2018-10-07.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, get_template_attribute, current_app, render_template
from jinja2 import Template, Environment

# language=jinja2
_status = """
{% if s.finished %}
    <span class="badge bg-primary">Finished</span>
    {% if s.solution_usable %}
        <span class="badge bg-success">Optimal solution</span>
    {% elif s.outcome == s.OUTCOME_NOT_SOLVED %}
        <span class="badge bg-warning text-dark">Not solved</span>
    {% elif s.outcome == s.OUTCOME_INFEASIBLE %}
        <span class="badge bg-danger">Infeasible</span>
    {% elif s.outcome == s.OUTCOME_UNBOUNDED %}
        <span class="badge bg-danger">Unbounded</span>
    {% elif s.outcome == s.OUTCOME_UNDEFINED %}
        <span class="badge bg-danger">Undefined</span>
    {% else %}
        <span class="badge bg-danger">Unknown outcome</span>
    {% endif %}
    <p></p>
    {% if s.solution_usable %}
        {% if s.draft_to_submitters is not none %}
            <span class="badge bg-info">Draft to submitters: {{ s.draft_to_submitters.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
        {% if s.draft_to_assessors is not none %}
            <span class="badge bg-info">Draft to assessors: {{ s.draft_to_assessors.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
        {% if s.final_to_submitters is not none %}
            <span class="badge bg-primary">Final to submitters: {{ s.final_to_submitters.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
        {% if s.final_to_assessors is not none %}
            <span class="badge bg-primary">Final to assessors: {{ s.final_to_assessors.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
    {% endif %}
    <p></p>
    {% if s.published and current_user.has_role('root') %}
        <span class="text-primary"><i class="fas fa-check-circle"></i> Published</span>
        (<a class="text-decoration-none" href="{{ url_for('admin.view_schedule', tag=s.tag) }}">public link</a>)
    {% endif %}
    {% if s.deployed and current_user.has_role('root') %}
        <span class="text-success"><i class="fas fa-check-circle"></i> Deployed</span>
        (<a class="text-decoration-none" href="{{ url_for('admin.view_schedule', tag=s.tag) }}">public link</a>)
    {% endif %}
{% else %}
    {% if s.awaiting_upload %}
        <span class="badge bg-success">Awaiting upload</span>
        {% if s.lp_file is not none %}
            <a class="text-decoration-none" href="{{ url_for('admin.download_generated_asset', asset_id=s.lp_file.id) }}">LP</a>
        {% endif %}
    {% else %}
        <span class="badge bg-success">In progress</span>
    {% endif %}
{% endif %}
"""


# language=jinja2
_timestamp = """
<div class="mt-2 text-muted small">
    Created by <i class="fas fa-user-circle"></i>
    <a class="text-decoration-none" href="mailto:{{ s.created_by.email }}">{{ s.created_by.name }}</a>
    {% if s.creation_timestamp is not none %}
        {{ s.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
    {% endif %}
</div>
</div>
{% if s.last_edited_by is not none %}
    <div class="mt-2 text-muted small">
        Last edited by <i class="fas fa-user-circle"></i>
        <a class="text-decoration-none" href="mailto:{{ s.last_edited_by.email }}">{{ s.last_edited_by.name }}</a>
        {% if s.last_edit_timestamp is not none %}
            {{ s.last_edit_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
        {% endif %}
    </div>
{% endif %}
"""


# language=jinja2
_score = """
{% if s.solution_usable %}
    <div class="text-success"><i class="fas fa-circle"></i> Original score {{ s.score }}</div>
{% else %}
    <div class="text-danger fw-semibold"><i class="fas fa-times-circle"></i> Invalid</div>
{% endif %}
"""


# language=jinja2
_name = """
<div>
    {% if s.finished and s.solution_usable %}
        <a class="text-decoration-none" href="{{ url_for('admin.schedule_view_sessions', id=s.id, text=text, url=url) }}">{{ s.name }}</a>
        <span class="badge bg-secondary">{{ s.tag }}</span>
        {% if s.has_issues %}
            <i class="fas fa-exclamation-triangle text-danger"></i>
        {% endif %}
    {% else %}
        {{ s.name }}
        <span class="badge bg-secondary">{{ s.tag }}</span>
    {% endif %}
</div>
{% if s.finished and s.solution_usable %}
    <div class="mt-2">
        {% if s.construct_time %}
            <div class="text-secondary small mt-1"><i class="fas fa-stopwatch"></i> Build {{ s.formatted_construct_time }}</div>
        {% endif %}
        {% if s.compute_time %}
            <span class="text-secondary small mt-1"><i class="fas fa-stopwatch"></i> Solve {{ s.formatted_compute_time }}</span>
        {% endif %}
    </div>
{% endif %}
"""


# language=jinja2
_info = """
<div class="d-flex flex-row justify-content-start align-items-start gap-2">
    <span class="small text-primary">Assignments &le; <strong>{{ s.assessor_assigned_limit }}</strong></span>
    <span class="small text-secondary">|</span>
    <span class="small text-primary">Session multiplicity &le; <strong>{{ s.assessor_multiplicity_per_session }}</strong></span>
    <span class="small text-secondary">|</span>
    <span class="small text-primary">If-needed cost <strong>{{ s.if_needed_cost }}</strong></span>
    <span class="small text-secondary">|</span>
    <span class="small text-primary">Levelling tension <strong>{{ s.levelling_tension }}</strong></span>
{% if s.ignore_coscheduling %}
    <span class="small text-secondary">|</span>
    <span class="small text-danger">Ignore coscheduling</span>
{% endif %}
</div>
<div class="mt-2 d-flex flex-row justify-content-start align-items-start gap-2">
{% if s.all_assessors_in_pool == s.ALL_IN_POOL %}
    <span class="small text-primary">Assessors in pool</span>
{% elif s.all_assessors_in_pool == s.AT_LEAST_ONE_IN_POOL %}
    <span class="small text-primary">&ge; 1 assessor in pool</span>
{% elif s.all_assessors_in_pool == s.ALL_IN_RESEARCH_GROUP %}
    <span class="small text-primary">Assessors in group</span>
{% elif s.all_assessors_in_pool == s. AT_LEAST_ONE_IN_RESEARCH_GROUP %}
    <span class="small text-primary">&ge; 1 assessor in group</span>
{% else %}
    <span class="badge bg-danger">Unknown pool setting</span>
{% endif %}
</div>
{% if s.finished and s.solution_usable %}
    <div class="mt-2 d-flex flex-row justify-content-start align-items start gap-2">
        {% set value = s.number_slots %}{% set pl = 's' %}{% if value == 1 %}{% set pl = '' %}{% endif %}
        <span class="small text-secondary">Uses {{ value }} slot{{ pl }}</span>
        {% set value = s.number_sessions %}{% set pl = 's' %}{% if value == 1 %}{% set pl = '' %}{% endif %}
        <span class="small text-secondary">|</span>
        <span class="small text-secondary">Uses {{ value }} session{{ pl }}</span>
        {% set value = s.number_rooms %}{% set pl = 's' %}{% if value == 1 %}{% set pl = '' %}{% endif %}
        <span class="small text-secondary">|</span>
        <span class="small text-secondary">Uses {{ value }} room{{ pl }}</span>
        {% set value = s.number_buildings %}{% set pl = 's' %}{% if value == 1 %}{% set pl = '' %}{% endif %}
        <span class="small text-secondary">|</span>
        <span class="small text-secondary">Uses {{ value }} building{{ pl }}</span>
        {% set value = s.number_ifneeded %}
        <span class="small text-secondary">|</span>
        <span class="small text-secondary">Uses 0 if-needed</span>
    </div>
{% endif %}
<div class="mt-2 d-flex flex-row justify-content-start align-items-start gap-2">
    <span class="text-success"><i class="fas fa-check-circle"></i> Solver {{ s.solver_name }}</span>
</div>
{% if s.has_issues %}
    <div class="mt-2 d-flex flex-column justify-content-start align-items-start gap-1">
        <div class="d-flex flex-row justify-content-start align-items-start gap-2">
            {% set errors = s.errors %}
            {% set warnings = s.warnings %}
            {% if errors|length == 1 %}
                <span class="badge bg-danger">1 error</span>
            {% elif errors|length > 1 %}
                <span class="badge bg-danger">{{ errors|length }} errors</span>
            {% endif %}
            {% if warnings|length == 1 %}
                <span class="badge bg-warning text-dark">1 warning</span>
            {% elif warnings|length > 1 %}
                <span class="badge bg-warning text-dark">{{ warnings|length }} warnings</span>
            {% endif %}
        </div>
        {% if errors|length > 0 %}
            {% for item in errors %}
                {% if loop.index <= 10 %}
                    <div class="text-danger small">{{ item }}</div>
                {% elif loop.index == 11 %}
                    <div class="text-danger small">Further errors suppressed...</div>
                {% endif %}            
            {% endfor %}
        {% endif %}
        {% if warnings|length > 0 %}
            {% for item in warnings %}
                {% if loop.index <= 10 %}
                    <div class="text-warning small">Warning: {{ item }}</div>
                {% elif loop.index == 11 %}
                    <div class="text-warning small">Further warnings suppressed...</div>
                {% endif %}
            {% endfor %}
        {% endif %}
    </div>
{% endif %}
"""

# language=jinja2
_menu = """
{% set valid = s.is_valid %}
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% if s.finished and s.solution_usable %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.schedule_view_sessions', id=s.id, text=text, url=url) }}">
                <i class="fas fa-search fa-fw"></i> Inspect schedule...
            </a>
            <div role="separator" class="dropdown-divider"></div>
        {% endif %}    

        {% if not s.finished %}
            {% set disabled = not current_user.has_role('root') %}
            {% if s.awaiting_upload %}
                <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.upload_schedule', schedule_id=s.id) }}"{% endif %}>
                    <i class="fas fa-cloud-upload-alt fa-fw"></i> Upload solution...
                </a>
                <div role="separator" class="dropdown-divider"></div>
            {% endif %}
            <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.duplicate_schedule', id=s.id) }}"{% endif %}>
                <i class="fas fa-clone fa-fw"></i> Duplicate
            </a>
            <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.terminate_schedule', id=s.id) }}"{% endif %}>
                <i class="fas fa-hand-paper fa-fw"></i> Terminate
            </a>
        {% else %}
            {% if s.solution_usable %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.rename_schedule', id=s.id, url=url) }}">
                    <i class="fas fa-pencil-alt fa-fw"></i> Rename...
                </a>
                {% if s.is_modified %}
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.revert_schedule', id=s.id) }}">
                        <i class="fas fa-undo fa-fw"></i> Revert to original
                    </a>
                {% endif %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.duplicate_schedule', id=s.id) }}">
                    <i class="fas fa-clone fa-fw"></i> Duplicate
                </a>
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.compare_schedule', id=s.id, url=url, text=text) }}">
                    <i class="fas fa-balance-scale fa-fw"></i> Compare to...
                </a>
                {% set disabled = valid %}
                <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.adjust_assessment_schedule', id=s.id) }}"{% endif %}>
                    <i class="fas fa-wrench fa-fw"></i> Impose constraints...
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-times fa-fw"></i> Solution is not usable</a>
            {% endif %}

            {% if current_user.has_role('root') or current_user.id == s.creator_id %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.delete_schedule', id=s.id) }}">
                    <i class="fas fa-trash fa-fw"></i> Delete
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-trash"></i> Delete</a>
            {% endif %}

            {% if current_user.has_role('root') %}
                <div role="separator" class="dropdown-divider"></div>
                <div class="dropdown-header">Superuser functions</div>

                {% if s.published %}
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.unpublish_schedule', id=s.id) }}">
                        <i class="fas fa-eject fa-fw"></i> Unpublish
                    </a>
                {% else %}
                    {% if not s.deployed %}
                        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.publish_schedule', id=s.id) }}">
                            <i class="fas fa-share-square fa-fw"></i> Publish to convenors
                        </a>
                    {% else %}
                        <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-ban"></i> Can't publish</a>
                    {% endif %}
                {% endif %}
                
                {% if s.deployed %}
                    {% if s.is_revokable %}
                        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.undeploy_schedule', id=s.id) }}">
                            <i class="fas fa-eject fa-fw"></i> Revoke deployment
                        </a>
                    {% else %}
                        <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-ban fa-fw"></i> Can't revoke</a>
                    {% endif %}
                {% else %}
                    {% if s.owner.is_deployed %}
                        <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-ban fa-fw"></i> Can't deploy</a>
                    {% else %}
                        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deploy_schedule', id=s.id) }}">
                            <i class="fas fa-play fa-fw"></i> Deploy
                        </a>
                    {% endif %}
                {% endif %}
                
                {% if s.published or s.deployed %}
                    <div role="separator" class="dropdown-divider"></div>
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.publish_schedule_submitters', id=s.id) }}">
                        <i class="fas fa-mail-bulk fa-fw"></i> Email to submitters
                    </a>
                    <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.publish_schedule_assessors', id=s.id) }}">
                        <i class="fas fa-mail-bulk fa-fw"></i> Email to assessors
                    </a>
                {% endif %}
            {% endif %}            
        {% endif %}        
    </div>
</div>
"""


# language=jinja2
_periods = """
{{ a.name }}
<p></p>
{% for period in a.submission_periods %}
    <div style="display: inline-block;">
        {{ simple_label(period.label) }}
        {% set num = period.number_projects %}
        {% set pl = 's' %}
        {% if num == 1 %}{% set pl = '' %}{% endif %}
        <span class="badge bg-info">{{ num }} project{{ pl }}</span>
    </div>
{% endfor %}
{% set total = a.number_talks %}
{% set missing = a.number_not_attending %}
{% if total > 0 or missing > 0 %}
    <p></p>
    {% set pl = 's' %}{% if total == 1 %}{% set p = '' %}{% endif %}
    <span class="badge bg-primary">{{ total }} presentation{{ pl }}</span>
    {% if missing > 0 %}
        <span class="badge bg-warning text-dark">{{ missing }} not attending</span>
    {% else %}
        <span class="badge bg-success">{{ missing }} not attending</span>
    {% endif %}
{% endif %}
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_status_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_status)


def _build_score_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_score)


def _build_timestamp_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_timestamp)


def _build_info_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_info)


def _build_periods_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_periods)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def assessment_schedules_data(schedules, text, url):
    """
    Build AJAX JSON payload
    :param schedules:
    :return:
    """
    simple_label = get_template_attribute("labels.html", "simple_label")

    name_templ: Template = _build_name_templ()
    status_templ: Template = _build_status_templ()
    score_templ: Template = _build_score_templ()
    timestamp_templ: Template = _build_timestamp_templ()
    info_templ: Template = _build_info_templ()
    periods_templ: Template = _build_periods_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "name": render_template(name_templ, s=s, text=text, url=url),
            "status": render_template(status_templ, s=s),
            "score": {"display": render_template(score_templ, s=s), "value": float(s.score) if s.solution_usable and s.score is not None else 0},
            "timestamp": render_template(timestamp_templ, s=s),
            "info": render_template(info_templ, s=s),
            "periods": render_template(periods_templ, a=s.owner, simple_label=simple_label),
            "menu": render_template(menu_templ, s=s, text=text, url=url),
        }
        for s in schedules
    ]

    return jsonify(data)
