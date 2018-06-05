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
{% for bookmark in project.bookmarks %}
    {% set student = bookmark.user %}
    <span class="label label-default">{{ student.user.build_name() }}</span>
{% endfor %}
"""

_pending = \
"""
{% for student in project.confirm_waiting %}
    <div class="dropdown">
        <button class="btn btn-success btn-sm dropdown-toggle" type="button"
                data-toggle="dropdown">
            <i class="fa fa-plus"></i> {{ student.user.build_name() }}
        </button>
        <ul class="dropdown-menu">
            {% if config.open %}
                <li>
                    <a href="{{ url_for('convenor.confirm', sid=student.id, pid=project.id) }}">
                        Confirm
                    </a>
                </li>
                <li>
                    <a href="{{ url_for('convenor.cancel_confirm', sid=student.id, pid=project.id) }}">
                        Remove
                    </a>
                </li>
            {% else %}
                <li class="disabled">
                    <a>Confirm</a>
                </li>
                <li class="disabled">
                    <a>Remove</a>
                </li>
            {% endif %}
        </ul>
    </div>
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
"""

_confirmed = \
"""
{% for student in project.confirmed_students %}
    <div class="dropdown">
        <button class="btn btn-warning btn-sm dropdown-toggle table-button" type="button"
                data-toggle="dropdown">
            <i class="fa fa-plus"></i> {{ student.user.build_name() }}
        </button>
        <ul class="dropdown-menu">
            {% if config.open %}
                <li>
                    <a href="{{ url_for('convenor.deconfirm', sid=student.id, pid=project.id) }}">
                        Remove
                    </a>
                </li>
                <li>
                    <a href="{{ url_for('convenor.deconfirm_to_pending', sid=student.id, pid=project.id) }}">
                        Make pending
                    </a>
                </li>
            {% else %}
                <li class="disabled">
                    <a>Remove</a>
                </li>
                <li class="disabled">
                    <a>Make pending</a>
                </li>
            {% endif %}
        </ul>
    </div>
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
"""

_menu = \
"""
<div class="dropdown">
    <button class="btn btn-success btn-sm btn-block dropdown-toggle table-button"
            type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('convenor.live_project', pid=project.id) }}">
                Preview web page
            </a>
        </li>
        {% if config.open and project.confirm_waiting and project.confirm_waiting.first() %}
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

        {% if config.open and project.confirmed_students and project.confirmed_students.first() %}
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

    data = []

    for project in config.live_projects:
        data.append({ 'number': '{c}'.format(c=project.number),
                      'name': '<a href="{url}">{name}</a>'.format(name=project.name,
                                                                  url=url_for('convenor.live_project', pid=project.id)),
                      'owner': '<a href="mailto:{em}">{name}</a>'.format(em=project.owner.email,
                                                                         name=project.owner.build_name()),
                      'group': '<span class="label label-success">{abrv}</span>'.format(abrv=project.group.abbreviation),
                      'bookmarks': render_template_string(_bookmarks, project=project),
                      'pending': render_template_string(_pending, project=project, config=config),
                      'confirmed': render_template_string(_confirmed, project=project, config=config),
                      'menu': render_template_string(_menu, project=project, config=config)
                    })

    return jsonify(data)
