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


_bookmarks = \
"""
{% set bookmarks = project.number_bookmarks %}
{% if bookmarks > 0 %}
    <span class="badge badge-info">{{ bookmarks }}</span>
    <a href="{{ url_for('convenor.project_bookmarks', id=project.id) }}">
       Show...
   </a>
{% else %}
    <span class="badge badge-secondary">None</span>
{% endif %}
"""

_selections = \
"""
{% set selections = project.number_selections %}
<div>
    {% if selections > 0 %}
        <span class="badge badge-primary">{{ selections }}</span>
        <a href="{{ url_for('convenor.project_choices', id=project.id) }}">
            Show...
        </a>
    {% else %}
        <span class="badge badge-secondary">None</span>
    {% endif %}
</div>
{% set offers = project.number_offers_accepted %}
{% if offers > 0 %}
    <div>
        {% for offer in project.custom_offers_accepted %}
            <span class="badge badge-success">Accepted: {{ offer.selector.student.user.name }}</span>
        {% endfor %}
    </div>
{% endif %}
"""

_confirmations = \
"""
{% set pending = project.number_pending %}
{% set confirmed = project.number_confirmed %}
<div>
    {% if confirmed > 0 %}<span class="badge badge-success"><i class="fa fa-check"></i> Confirmed {{ confirmed }}</span>{% endif %}
    {% if pending > 0 %}<span class="badge badge-warning"><i class="fa fa-clock-o"></i> Pending {{ pending }}</span>{% endif %}
    {% if pending > 0 or confirmed > 0 %}
        <a href="{{ url_for('convenor.project_confirmations', id=project.id) }}">
            Show...
        </a>
    {% else %}
        <span class="badge badge-secondary">None</span>
    {% endif %}
</div>
{% set offers = project.number_offers_pending + project.number_offers_declined %}
{% if offers > 0 %}
    <div>
        {% for offer in project.custom_offers_pending %}
            <span class="badge badge-primary">Offer: {{ offer.selector.student.user.name }}</span>
        {% endfor %}
        {% for offer in project.custom_offers_declined %}
            <span class="badge badge-secondary">Declined: {{ offer.selector.student.user.name }}</span>
        {% endfor %}
    </div>
{% endif %}
"""

_popularity = \
"""
{% set R = project.popularity_rank(live=require_live) %}
{% if R is not none %}
    {% set rank, total = R %}
    <a href="{{ url_for('reports.liveproject_analytics', pane='popularity', proj_id=project.id, url=url, text=text) }}" class="badge badge-primary">Popularity {{ rank }}/{{ total }}</a>
{% else %}
    <span class="badge badge-secondary">Popularity updating...</span>
{% endif %}
{% set R = project.views_rank(live=require_live) %}
{% if R is not none %}
    {% set rank, total = R %}
    <a href="{{ url_for('reports.liveproject_analytics', pane='views', proj_id=project.id, url=url, text=text) }}" class="badge badge-secondary">Views {{ rank }}/{{ total }}</a>
{% else %}
    <span class="badge badge-secondary">Views updating...</span>
{% endif %}
"""

_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle table-button" type="button" data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <a class="dropdown-item" href="{{ url_for('faculty.live_project', pid=project.id, text='live projects list', url=url_for('convenor.liveprojects', id=config.pclass_id)) }}">
            <i class="fa fa-eye"></i> View web page
        </a>
        <a class="dropdown-item" href="{{ url_for('reports.liveproject_analytics', pane='popularity', proj_id=project.id, url=url, text=text) }}">
            <i class="fa fa-wrench"></i> View analytics
        </a>
        <a class="dropdown-item" href="{{ url_for('convenor.delete_live_project', pid=project.id) }}">
            <i class="fa fa-trash"></i> Delete
        </a>
        
        <div role="separator" class="dropdown-divider">

        {% if project.number_bookmarks > 0 %}
            <a class="dropdown-item" href="{{ url_for('convenor.project_bookmarks', id=project.id) }}">
                <i class="fa fa-cogs"></i> Bookmarking students
            </a>
        {% else %}
            <a class="dropdown-item disabled">><i class="fa fa-cogs"></i> Bookmarking students</a>
        {% endif %}
        
        {% if project.number_selections > 0 %}
            <a class="dropdown-item" href="{{ url_for('convenor.project_choices', id=project.id) }}">
                <i class="fa fa-cogs"></i> Selecting students
            </a>
        {% else %}
            <a class="dropdown-item disabled"><i class="fa fa-cogs"></i> Selecting students</a>
        {% endif %}
        <a class="dropdown-item" href="{{ url_for('convenor.project_custom_offers', proj_id=project.id) }}">
            <i class="fa fa-cogs"></i> Custom offers...
        </a>

        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Meeting requests</div>
        {% if config.selector_lifecycle == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and project.number_pending > 0 %}
            <a class="dropdown-item" href="{{ url_for('convenor.project_confirm_all', pid=project.id) }}">
                <i class="fa fa-check"></i> Confirm all requests
            </a>
            <a class="dropdown-item" href="{{ url_for('convenor.project_clear_requests', pid=project.id) }}">
                <i class="fa fa-trash"></i> Delete all requests
            </a>
        {% else %}
            <a class="dropdown-item disabled">
                <i class="fa fa-check"></i> Confirm all requests
            </a>
            <a class="dropdown-item disabled">
                <i class="fa fa-trash"></i> Delete all requests
            </a>
        {% endif %}

        <div role="separator" class="dropdown-divider"></div>
        div class="dropdown-header">Meeting confirmations</div>
        {% if config.selector_lifecycle == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and project.number_confirmed > 0 %}
            <a class="dropdown-item" href="{{ url_for('convenor.project_remove_confirms', pid=project.id) }}">
                <i class="fa fa-trash"></i> Delete confirmations
            </a>
            <a class="dropdown-item" href="{{ url_for('convenor.project_make_all_confirms_pending', pid=project.id) }}">
                <i class="fa fa-clock-o"></i> Make all pending
            </a>
        {% else %}
            <a class="dropdown-item disabled">
                <i class="fa fa-trash"></i> Delete confirmations
            </a>
            <a class="dropdown-item disabled">
                <i class="fa fa-clock-o"></i> Make all pending
            </a>
        {% endif %}
        
        {% if project.number_pending > 0 or project.number_confirmed > 0 %}
            <a class="dropdown-item" href="{{ url_for('convenor.project_confirmations', id=project.id) }}">
                <i class="fa fa-cogs"></i> Show confirmations
            </a>
        {% else %}
            <a class="dropdown-item disabled">
                <i class="fa fa-cogs"></i> Show confirmations
            </a>
        {% endif %}
    </div>
</div>
"""


def liveprojects_data(config: ProjectClassConfig, projects, url=None, text=None):

    lifecycle = config.selector_lifecycle
    require_live = (lifecycle==ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN)

    def get_popularity_rank(p):
        data = p.popularity_rank(live=require_live)

        if data is None:
            return -1

        rank, total = data
        return rank

    data = [{'number': '{c}'.format(c=p.number),
             'name': '<a href="{url}">{name}</a>'.format(name=p.name,
                                                         url=url_for('faculty.live_project', pid=p.id,
                                                                     text='live projects list',
                                                                     url=url_for('convenor.liveprojects', id=config.pclass_id))),
             'owner': '<a href="mailto:{em}">{name}</a>'.format(em=p.owner.user.email,
                                                                name=p.owner.user.name),
             'group': p.group.make_label(),
             'bookmarks': {
                 'display': render_template_string(_bookmarks, project=p),
                 'value': p.number_bookmarks
             },
             'selections': {
                 'display': render_template_string(_selections, project=p),
                 'value': p.number_selections
             },
             'confirmations': {
                 'display': render_template_string(_confirmations, project=p),
                 'value': p.number_pending + p.number_confirmed
             },
             'popularity': {
                 'display': render_template_string(_popularity, project=p, require_live=require_live, url=url, text=text),
                 'value': get_popularity_rank(p)
             },
             'menu': render_template_string(_menu, project=p, config=config, url=url, text=text)} for p in projects]

    return jsonify(data)
