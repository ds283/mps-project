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


_available = \
"""
<div class="row">
    <div class="col-xs-7">
        {% if project.meeting_reqd == project.MEETING_REQUIRED %}
            <span class="label label-danger">Meeting required</span>
        {% elif project.meeting_reqd == project.MEETING_OPTIONAL %}
            <span class="label label-warning">Meeting optional</span>
        {% else %}
            <span class="label label-default">Meeting not required</span>
        {% endif %}
    </div>
    <div class="col-xs-5">
        <div class="pull-right">
            {% if project.is_available(sel) %}
                <span class="label label-success">Available</span>
            {% else %}
                {% if sel in project.confirm_waiting %}
                    <a href="{{ url_for('student.cancel_confirmation', sid=sel.id, pid=project.id) }}" class="btn btn-warning btn-sm table-button">
                        Cancel
                    </a>
                {% else %}
                    <a href="{{ url_for('student.request_confirmation', sid=sel.id, pid=project.id) }}" class="btn btn-default btn-sm table-button">
                        Request
                    </a>
                {% endif %}
            {% endif %}
        </div>
    </div>
</div>
"""

_bookmarks = \
"""
{% set bookmarked = false %}
{% if sel.bookmarks.filter_by(liveproject_id=project.id).first() %}
    {% set bookmarked = true %}
    <div class="row vertical-align">
        <div class="col-xs-4">
            <span class="label label-primary">Yes</span>
        </div>
        <div class="col-xs-8">
            <div class="pull-right">
                <a href="{{ url_for('student.remove_bookmark', sid=sel.id, pid=project.id) }}" class="btn btn-default btn-sm">
                    Remove
                </a>
            </div>
        </div>
    </div>
{% else %}
    <div class="row vertical-align">
        <div class="col-xs-5">
            <span class="label label-default">No</span>
        </div>
        <div class="col-xs-7">
            <div class="pull-right">
                <a href="{{ url_for('student.add_bookmark', sid=sel.id, pid=project.id) }}" class="btn btn-default btn-sm">
                    Add
                </a>
            </div>
        </div>
    </div>
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
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('student.view_project', sid=sel.id, pid=project.id) }}">
                View project
            </a>
        </li>
        <li>
            {% if bookmarked %}
                <a href="{{ url_for('student.remove_bookmark', sid=sel.id, pid=project.id) }}">
                    Remove bookmark
                </a>
            {% else %}
                <a href="{{ url_for('student.add_bookmark', sid=sel.id, pid=project.id) }}">
                    Add bookmark
                </a>
            {% endif %}
        </li>
        <li {% if project.is_available(sel) %}class="disabled"{% endif %}>
            {% if not project.is_available(sel) %}
                {% if sel in project.confirm_waiting %}
                    <a href="{{ url_for('student.cancel_confirmation', sid=sel.id, pid=project.id) }}">
                        Cancel confirmation
                    </a>
                {% else %}
                    <a href="{{ url_for('student.request_confirmation', sid=sel.id, pid=project.id) }}">
                        Request confirmation
                    </a>
                {% endif %}
            {% else %}
                <a>Project available</a>
            {% endif %}
        </li>
    </ul>
</div>
"""

_project_prefer = \
"""
{% for programme in project.programmes %}
    {% if programme.active %}
        {{ programme.label()|safe }}
    {% endif %}
{% endfor %}
"""

_project_skills = \
"""
{% for skill in skills %}
    {% if skill.is_active %}
      {{ skill.make_label()|safe }}
    {% endif %}
{% endfor %}
"""

def liveprojects_data(sel, projects):
    data = [{'number': '{c}'.format(c=p.number),
             'name': '<a href="{url}">{name}</strong></a>'.format(name=p.name,
                                                                  url=url_for('student.view_project', sid=sel.id,
                                                                              pid=p.id)),
             'supervisor': '{name} <a href="mailto:{em}">{em}</a>'.format(name=p.owner.build_name(),
                                                                         em=p.owner.email),
             'group': p.group.make_label(p.group.name),
             'skills': render_template_string(_project_skills, skills=p.ordered_skills),
             'prefer': render_template_string(_project_prefer, project=p),
             'available': render_template_string(_available, sel=sel, project=p),
             'bookmarks': render_template_string(_bookmarks, sel=sel, project=p),
             'menu': render_template_string(_menu, sel=sel, project=p)} for p in projects]

    return jsonify(data)
