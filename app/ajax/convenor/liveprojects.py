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
       Show ...
   </a>
{% else %}
    <span class="label label-default">None</span>
{% endif %}
"""

_selections = \
"""
{% set selections = project.number_selections %}
{% if selections > 0 %}
    <span class="label label-primary">{{ selections }}</span>
    <a href="{{ url_for('convenor.project_choices', id=project.id) }}">
        Show ...
    </a>
{% else %}
    <span class="label label-default">None</span>
{% endif %}
"""

_confirmations = \
"""
{% set pending = project.number_pending %}
{% set confirmed = project.number_confirmed %}
{% if confirmed > 0 %}<span class="label label-success"><i class="fa fa-check"></i> Confirmed {{ confirmed }}</span>{% endif %}
{% if pending > 0 %}<span class="label label-warning"><i class="fa fa-clock-o"></i> Pending {{ pending }}</span>{% endif %}
{% if pending > 0 or confirmed > 0 %}
    <a href="{{ url_for('convenor.project_confirmations', id=project.id) }}">
        Show ...
    </a>
{% else %}
    <span class="label label-default">None</span>
{% endif %}
"""

_popularity = \
"""
{% set R = project.popularity_rank %}
{% if R is not none %}
    {% set rank, total = R %}
    <span class="label label-success">Rank {{ rank }}/{{ total }}</span>
{% else %}
    <span class="label label-default">Not available</span>>
{% endif %}
"""

_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle table-button"
            type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('faculty.live_project', pid=project.id) }}">
                View web page
            </a>
        </li>
        {% if config.state == config.LIFECYCLE_SELECTIONS_OPEN and project.confirm_waiting and project.confirm_waiting.first() %}
            <li>
                <a href="{{ url_for('convenor.project_confirm_all', pid=project.id) }}">
                    Confirm all requests
                </a>
                <a href="{{ url_for('convenor.project_clear_requests', pid=project.id) }}">
                    Clear all requests
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>Confirm all requests</a>
            </li>
            <li class="disabled">
                <a>Clear all requests</a>
            </li>
        {% endif %}

        {% if config.state == config.LIFECYCLE_SELECTIONS_OPEN and project.confirmed_students and project.confirmed_students.first() %}
            <li>
                <a href="{{ url_for('convenor.project_remove_confirms', pid=project.id) }}">
                    Remove confirmations
                </a>
                <a href="{{ url_for('convenor.project_make_all_confirms_pending', pid=project.id) }}">
                    Make all pending
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>Remove confirmations</a>
            </li>
            <li class="disabled">
                <a>Make all pending</a>
            </li>
        {% endif %}
    </ul>
</div>
"""


def liveprojects_data(config):

    data = [{'number': '{c}'.format(c=p.number),
             'name': '<a href="{url}">{name}</a>'.format(name=p.name,
                                                         url=url_for('faculty.live_project', pid=p.id)),
             'owner': '<a href="mailto:{em}">{name}</a>'.format(em=p.owner.email,
                                                                name=p.owner.build_name()),
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
                 'display': render_template_string(_popularity, project=p),
                 'value': p.popularity_rank[0] if p.popularity_rank is not None else 0
             },
             'menu': render_template_string(_menu, project=p, config=config)} for p in config.live_projects]

    return jsonify(data)
