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

from ...database import db
from ...models import ConfirmRequest, SelectingStudent, LiveProject, Bookmark
from ...cache import cache

from sqlalchemy.event import listens_for


_meeting = \
"""
{% if project.meeting_reqd == project.MEETING_REQUIRED %}
    {% if project.is_confirmed(sel) %}
        <span class="badge badge-primary"><i class="fa fa-check"></i> Confirmed</span>
    {% else %}
        <span class="badge badge-danger"><i class="fa fa-times"></i> Required</span>
    {% endif %}
{% elif project.meeting_reqd == project.MEETING_OPTIONAL %}
    <span class="badge badge-warning">Optional</span>
{% else %}
    <span class="badge badge-default"><i class="fa fa-check"></i> Not required</span>
{% endif %}
"""


_status = \
"""
{% if project.is_available(sel) %}
    <span class="badge badge-success"><i class="fa fa-check"></i> Available for selection</span>
{% else %}
    {% if project.is_waiting(sel) %}
        <a href="{{ url_for('student.cancel_confirmation', sid=sel.id, pid=project.id) }}" class="badge badge-warning">
            <i class="fa fa-times"></i> Cancel request
        </a>
    {% else %}
        <a href="{{ url_for('student.request_confirmation', sid=sel.id, pid=project.id) }}" class="badge badge-primary">
            <i class="fa fa-plus"></i> Request confirmation
        </a>
    {% endif %}
{% endif %}
"""

_bookmarks = \
"""
{% if sel.is_project_bookmarked(project) %}
    <a href="{{ url_for('student.remove_bookmark', sid=sel.id, pid=project.id) }}"
       class="badge badge-primary">
       <i class="fa fa-times"></i> Remove
    </a>
{% else %}
    <a href="{{ url_for('student.add_bookmark', sid=sel.id, pid=project.id) }}"
       class="badge badge-default">
       <i class="fa fa-plus"></i> Add
    </a>
{% endif %}
"""

_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button"
            data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('student.view_project', sid=sel.id, pid=project.id) }}">
                View project...
            </a>
        </li>
        {% if is_live %}
            <li>
                {% if sel.is_project_bookmarked(project) %}
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
                    {% if project.is_waiting(sel) %}
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
        {% else %}
            <li role="separator" class="divider">
            <li class="disabled">
                <a>Project selection not live</a>
            </li>
        {% endif %}
    </ul>
</div>
"""

_project_prefer = \
"""
{% for programme in project.programmes %}
    {% if programme.active %}
        {{ programme.label|safe }}
    {% endif %}
{% endfor %}
"""

_project_skills = \
"""
{% for skill in skills %}
    {% if skill.is_active %}
        {% if skill.group is none %}
            {{ skill.make_label()|safe }}
        {% else %}
            <a href="{{ url_for('student.add_skill_filter', id=sel.id, skill_id=skill.id) }}" class="badge badge-default" style="{{ skill.group.make_CSS_style() }}">{%- if skill.group.add_group -%}{{ skill.group.name }}:{% endif %} {{ skill.name }}</a>
        {% endif %}
    {% endif %}
{% endfor %}
"""


_project_group = \
"""
<a href="{{ url_for('student.add_group_filter', id=sel.id, gid=group.id) }}"
   class="badge badge-default" style="{{ group.make_CSS_style() }}">
   {{ group.name }}
</a>
"""


_not_live = \
"""
<span class="badge badge-default">Not live</span>
"""


@cache.memoize()
def _element(sel_id, project_id, is_live):
    sel = db.session.query(SelectingStudent).filter_by(id=sel_id).one()
    p = db.session.query(LiveProject).filter_by(id=project_id).one()

    return {'number': '{c}'.format(c=p.number),
             'name': '<a href="{url}">{name}</a>'.format(name=p.name,
                                                         url=url_for('student.view_project', sid=sel.id, pid=p.id)),
             'supervisor': {
                 'display': '{name} <a href="mailto:{em}">{em}</a>'.format(name=p.owner.user.name,
                                                                           em=p.owner.user.email),
                 'sortvalue': p.owner.user.last_name + p.owner.user.first_name},
             'group': render_template_string(_project_group, sel=sel, group=p.group),
             'skills': render_template_string(_project_skills, sel=sel, skills=p.ordered_skills),
             'prefer': render_template_string(_project_prefer, project=p),
             'meeting': render_template_string(_meeting, sel=sel, project=p),
             'availability': render_template_string(_status, sel=sel, project=p) if is_live else
                             render_template_string(_not_live),
             'bookmarks': render_template_string(_bookmarks, sel=sel, project=p) if is_live else
                          render_template_string(_not_live),
             'menu': render_template_string(_menu, sel=sel, project=p, is_live=is_live)}


def _delete_browsing_cache(owner_id, project_id):
    cache.delete_memoized(_element, owner_id, project_id, True)
    cache.delete_memoized(_element, owner_id, project_id, False)


@listens_for(ConfirmRequest, 'before_insert')
def _ConfirmRequest_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_browsing_cache(target.owner_id, target.project_id)


@listens_for(ConfirmRequest, 'before_update')
def _ConfirmRequest_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_browsing_cache(target.owner_id, target.project_id)


@listens_for(ConfirmRequest, 'before_delete')
def _ConfirmRequest_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_browsing_cache(target.owner_id, target.project_id)


@listens_for(Bookmark, 'before_update')
def _Bookmark_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_browsing_cache(target.owner_id, target.liveproject_id)


@listens_for(Bookmark, 'before_insert')
def _Bookmark_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_browsing_cache(target.owner_id, target.liveproject_id)


@listens_for(Bookmark, 'before_delete')
def _Bookmark_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        _delete_browsing_cache(target.owner_id, target.liveproject_id)


def liveprojects_data(sel_id, projects, is_live=True):
    data = [_element(sel_id, project_id, is_live) for project_id in projects]

    return jsonify(data)
