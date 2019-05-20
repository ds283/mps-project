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


_bookmarks = \
"""
{% set bookmarks = project.number_bookmarks %}
{% if bookmarks > 0 %}
    <span class="label label-info">{{ bookmarks }}</span>
    <a href="{{ url_for('convenor.project_bookmarks', id=project.id) }}">
       Show...
   </a>
{% else %}
    <span class="label label-default">None</span>
{% endif %}
"""

_selections = \
"""
{% set selections = project.number_selections %}
<div>
    {% if selections > 0 %}
        <span class="label label-primary">{{ selections }}</span>
        <a href="{{ url_for('convenor.project_choices', id=project.id) }}">
            Show...
        </a>
    {% else %}
        <span class="label label-default">None</span>
    {% endif %}
</div>
{% set offers = project.number_offers_accepted %}
{% if offers > 0 %}
    <div>
        {% for offer in project.custom_offers_accepted %}
            <span class="label label-success">Accepted: {{ offer.selector.student.user.name }}</span>
        {% endfor %}
    </div>
{% endif %}
"""

_confirmations = \
"""
{% set pending = project.number_pending %}
{% set confirmed = project.number_confirmed %}
<div>
    {% if confirmed > 0 %}<span class="label label-success"><i class="fa fa-check"></i> Confirmed {{ confirmed }}</span>{% endif %}
    {% if pending > 0 %}<span class="label label-warning"><i class="fa fa-clock-o"></i> Pending {{ pending }}</span>{% endif %}
    {% if pending > 0 or confirmed > 0 %}
        <a href="{{ url_for('convenor.project_confirmations', id=project.id) }}">
            Show...
        </a>
    {% else %}
        <span class="label label-default">None</span>
    {% endif %}
</div>
{% set offers = project.number_offers_pending + project.number_offers_declined %}
{% if offers > 0 %}
    <div>
        {% for offer in project.custom_offers_pending %}
            <span class="label label-primary">Offer: {{ offer.selector.student.user.name }}</span>
        {% endfor %}
        {% for offer in project.custom_offers_declined %}
            <span class="label label-default">Declined: {{ offer.selector.student.user.name }}</span>
        {% endfor %}
    </div>
{% endif %}
"""

_popularity = \
"""
{% set R = project.popularity_rank(live=True) %}
{% if R is not none %}
    {% set rank, total = R %}
    <a href="{{ url_for('reports.liveproject_analytics', pane='popularity', proj_id=project.id, url=url, text=text) }}" class="label label-primary">Popularity {{ rank }}/{{ total }}</a>
{% else %}
    <span class="label label-default">Popularity updating...</span>
{% endif %}
{% set R = project.views_rank(live=True) %}
{% if R is not none %}
    {% set rank, total = R %}
    <a href="{{ url_for('reports.liveproject_analytics', pane='views', proj_id=project.id, url=url, text=text) }}" class="label label-default">Views {{ rank }}/{{ total }}</a>
{% else %}
    <span class="label label-default">Views updating...</span>
{% endif %}
"""

_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle table-button" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('faculty.live_project', pid=project.id, text='live projects list', url=url_for('convenor.liveprojects', id=config.pclass_id)) }}">
                <i class="fa fa-eye"></i> View web page
            </a>
        </li>
        <li>
            <a href="{{ url_for('reports.liveproject_analytics', pane='popularity', proj_id=project.id, url=url, text=text) }}">
                <i class="fa fa-wrench"></i> View analytics
            </a>
        </li>
        
        <li role="separator" class="divider">

        {% if project.number_bookmarks > 0 %}
            <li>
                <a href="{{ url_for('convenor.project_bookmarks', id=project.id) }}">
                    <i class="fa fa-cogs"></i> Bookmarking students
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a><i class="fa fa-cogs"></i> Bookmarking students</a>
            </li>
        {% endif %}
        
        {% if project.number_selections > 0 %}
            <li>
                <a href="{{ url_for('convenor.project_choices', id=project.id) }}">
                    <i class="fa fa-cogs"></i> Selecting students
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a><i class="fa fa-cogs"></i> Selecting students</a>
            </li>
        {% endif %}
        <li>
            <a href="{{ url_for('convenor.project_custom_offers', proj_id=project.id) }}">
                <i class="fa fa-cogs"></i> Custom offers...
            </a>
        </li>

        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Meeting requests</li>
        {% if config.selector_lifecycle == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and project.number_pending > 0 %}
            <li>
                <a href="{{ url_for('convenor.project_confirm_all', pid=project.id) }}">
                    <i class="fa fa-check"></i> Confirm all requests
                </a>
                <a href="{{ url_for('convenor.project_clear_requests', pid=project.id) }}">
                    <i class="fa fa-trash"></i> Delete all requests
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>
                    <i class="fa fa-check"></i> Confirm all requests
                </a>
            </li>
            <li class="disabled">
                <a>
                    <i class="fa fa-trash"></i> Delete all requests
                </a>
            </li>
        {% endif %}

        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Meeting confirmations</li>
        {% if config.selector_lifecycle == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN and project.number_confirmed > 0 %}
            <li>
                <a href="{{ url_for('convenor.project_remove_confirms', pid=project.id) }}">
                    <i class="fa fa-trash"></i> Delete confirmations
                </a>
                <a href="{{ url_for('convenor.project_make_all_confirms_pending', pid=project.id) }}">
                    <i class="fa fa-clock-o"></i> Make all pending
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>
                    <i class="fa fa-trash"></i> Delete confirmations
                </a>
            </li>
            <li class="disabled">
                <a>
                    <i class="fa fa-clock-o"></i> Make all pending
                </a>
            </li>
        {% endif %}
        
        {% if project.number_pending > 0 or project.number_confirmed > 0 %}
            <li>
                <a href="{{ url_for('convenor.project_confirmations', id=project.id) }}">
                    <i class="fa fa-cogs"></i> Show confirmations
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>
                    <i class="fa fa-cogs"></i> Show confirmations
                </a>
            </li>
        {% endif %}
    </ul>
</div>
"""


def liveprojects_data(config, projects, url=None, text=None):

    def get_popularity_rank(p):
        data = p.popularity_rank(live=True)

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
                 'display': render_template_string(_popularity, project=p, url=url, text=text),
                 'value': get_popularity_rank(p)
             },
             'menu': render_template_string(_menu, project=p, config=config, url=url, text=text)} for p in projects]

    return jsonify(data)
