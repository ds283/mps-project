#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for

from ...models import ProjectClassConfig


# language=jinja2
_name = \
"""
<a class="text-decoration-none" href="{{ url_for('faculty.live_project', pid=project.id, text='live projects list', url=url_for('convenor.liveprojects', id=config.pclass_id)) }}">{{ project.name }}</a>
{% if project.hidden %}
    <div>
        <span class="badge bg-danger"><i class="fas fa-eye-slash"></i> HIDDEN</span>
    </div>
{% endif %}
"""


# language=jinja2
_owner = \
"""
{% if project.generic %}
    <span class="badge bg-info">Generic</span>
{% else %}
    {% if project.owner is not none %}
        <a class="text-decoration-none" href="mailto:{{ project.owner.user.email }}">{{ project.owner.user.name }}</a>
    {% else %}
        <span class="badge bg-danger">Missing</span>
    {% endif %}
{% endif %}
"""


# language=jinja2
_affiliation = \
"""
{% set ns = namespace(affiliation=false) %}
{% if project.group %}
    {{ project.group.make_label()|safe }}
    {% set ns.affiliation = true %}
{% endif %}
{% for tag in project.forced_group_tags %}
    {% if tag.name|length > 15 %}
        {{ tag.make_label(tag.name[0:15]+'...')|safe }}
    {% else %}
        {{ tag.make_label()|safe }}
    {% endif %}
    {% set ns.affiliation = true %}
{% endfor %}
{% if not ns.affiliation %}
    <span class="badge bg-warning text-dark">No affiliations</span>
{% endif %}
"""


# language=jinja2
_bookmarks = \
"""
{% set bookmarks = project.number_bookmarks %}
{% if bookmarks > 0 %}
    <span class="badge bg-info text-dark">{{ bookmarks }}</span>
    <a class="text-decoration-none" href="{{ url_for('convenor.project_bookmarks', id=project.id) }}">
       Show...
   </a>
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""

# language=jinja2
_selections = \
"""
{% set selections = project.number_selections %}
<div>
    {% if selections > 0 %}
        <span class="badge bg-primary">{{ selections }}</span>
        <a class="text-decoration-none" href="{{ url_for('convenor.project_choices', id=project.id) }}">
            Show...
        </a>
    {% else %}
        <span class="badge bg-secondary">None</span>
    {% endif %}
</div>
{% set offers = project.number_offers_accepted %}
{% if offers > 0 %}
    <div>
        {% for offer in project.custom_offers_accepted %}
            <span class="badge bg-success">Accepted: {{ offer.selector.student.user.name }}</span>
        {% endfor %}
    </div>
{% endif %}
"""

# language=jinja2
_confirmations = \
"""
{% set pending = project.number_pending %}
{% set confirmed = project.number_confirmed %}
<div>
    {% if confirmed > 0 %}<span class="badge bg-success"><i class="fas fa-check"></i> Confirmed {{ confirmed }}</span>{% endif %}
    {% if pending > 0 %}<span class="badge bg-warning text-dark"><i class="fas fa-clock"></i> Pending {{ pending }}</span>{% endif %}
    {% if pending > 0 or confirmed > 0 %}
        <a class="text-decoration-none" href="{{ url_for('convenor.project_confirmations', id=project.id) }}">
            Show...
        </a>
    {% else %}
        <span class="badge bg-secondary">None</span>
    {% endif %}
</div>
{% set offers = project.number_offers_pending + project.number_offers_declined %}
{% if offers > 0 %}
    <div>
        {% for offer in project.custom_offers_pending %}
            <span class="badge bg-primary">Offer: {{ offer.selector.student.user.name }}</span>
        {% endfor %}
        {% for offer in project.custom_offers_declined %}
            <span class="badge bg-secondary">Declined: {{ offer.selector.student.user.name }}</span>
        {% endfor %}
    </div>
{% endif %}
"""

# language=jinja2
_popularity = \
"""
{% set R = project.popularity_rank(live=require_live) %}
{% if R is not none %}
    {% set rank, total = R %}
    <a href="{{ url_for('reports.liveproject_analytics', pane='popularity', proj_id=project.id, url=url, text=text) }}" class="badge bg-primary text-decoration-none">Popularity {{ rank }}/{{ total }}</a>
{% else %}
    <span class="badge bg-secondary">Popularity updating...</span>
{% endif %}
{% set R = project.views_rank(live=require_live) %}
{% if R is not none %}
    {% set rank, total = R %}
    <a href="{{ url_for('reports.liveproject_analytics', pane='views', proj_id=project.id, url=url, text=text) }}" class="badge bg-secondary text-decoration-none">Views {{ rank }}/{{ total }}</a>
{% else %}
    <span class="badge bg-secondary">Views updating...</span>
{% endif %}
"""

# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle table-button" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.live_project', pid=project.id, text='live projects list', url=url_for('convenor.liveprojects', id=config.pclass_id)) }}">
            <i class="fas fa-eye fa-fw"></i> View web page
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('reports.liveproject_analytics', pane='popularity', proj_id=project.id, url=url, text=text) }}">
            <i class="fas fa-wrench fa-fw"></i> View analytics
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.delete_live_project', pid=project.id) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
        {% if project.hidden %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.unhide_liveproject', id=project.id) }}">
                <i class="fas fa-eye fa-fw"></i> Unhide
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.hide_liveproject', id=project.id) }}">
                <i class="fas fa-eye-slash fa-fw"></i> Hide
            </a>
        {% endif %}        
        <div role="separator" class="dropdown-divider">
        {% if project.number_bookmarks > 0 %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_bookmarks', id=project.id) }}">
                <i class="fas fa-cogs fa-fw"></i> Bookmarking students
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled">><i class="fas fa-cogs fa-fw"></i> Bookmarking students</a>
        {% endif %}
        
        {% if project.number_selections > 0 %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_choices', id=project.id) }}">
                <i class="fas fa-cogs fa-fw"></i> Selecting students
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-cogs fa-fw"></i> Selecting students</a>
        {% endif %}
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_custom_offers', proj_id=project.id) }}">
            <i class="fas fa-cogs fa-fw"></i> Custom offers...
        </a>

        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Meeting requests</div>
        {% if config.selector_lifecycle == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and project.number_pending > 0 %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_confirm_all', pid=project.id) }}">
                <i class="fas fa-check fa-fw"></i> Confirm all requests
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_clear_requests', pid=project.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete all requests
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled">
                <i class="fas fa-check fa-fw"></i> Confirm all requests
            </a>
            <a class="dropdown-item d-flex gap-2 disabled">
                <i class="fas fa-trash fa-fw"></i> Delete all requests
            </a>
        {% endif %}

        <div role="separator" class="dropdown-divider"></div>
        div class="dropdown-header">Meeting confirmations</div>
        {% if config.selector_lifecycle == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and project.number_confirmed > 0 %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_remove_confirms', pid=project.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete confirmations
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_make_all_confirms_pending', pid=project.id) }}">
                <i class="fas fa-clock fa-fw"></i> Make all pending
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled">
                <i class="fas fa-trash fa-fw"></i> Delete confirmations
            </a>
            <a class="dropdown-item d-flex gap-2 disabled">
                <i class="fas fa-clock fa-fw"></i> Make all pending
            </a>
        {% endif %}
        
        {% if project.number_pending > 0 or project.number_confirmed > 0 %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.project_confirmations', id=project.id) }}">
                <i class="fas fa-cogs fa-fw"></i> Show confirmations
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled">
                <i class="fas fa-cogs fa-fw"></i> Show confirmations
            </a>
        {% endif %}
    </div>
</div>
"""


def liveprojects_data(projects, config: ProjectClassConfig, url=None, text=None):
    lifecycle = config.selector_lifecycle
    require_live = (lifecycle == ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN)

    data = [{'name': render_template_string(_name, project=p, config=config),
             'owner': render_template_string(_owner, project=p),
             'group': render_template_string(_affiliation, project=p),
             'bookmarks': render_template_string(_bookmarks, project=p),
             'selections': render_template_string(_selections, project=p),
             'confirmations': render_template_string(_confirmations, project=p),
             'popularity': render_template_string(_popularity, project=p, require_live=require_live, url=url, text=text),
             'menu': render_template_string(_menu, project=p, config=config, url=url, text=text)} for p in projects]

    return data
