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
    {% if sel %}
        {% if project.is_confirmed(sel) %}
            <span class="badge badge-primary"><i class="fas fa-check"></i> Confirmed</span>
        {% else %}
            <span class="badge badge-danger"><i class="fas fa-times"></i> Required</span>
        {% endif %}
    {% else %}
        <span class="badge badge-secondary">Not live</span>
    {% endif %}
{% elif project.meeting_reqd == project.MEETING_OPTIONAL %}
    <span class="badge badge-warning">Optional</span>
{% else %}
    <span class="badge badge-secondary"><i class="fas fa-check"></i> Not required</span>
{% endif %}
"""


_status = \
"""
{% if sel %}
    {% if project.is_available(sel) %}
        <span class="badge badge-success"><i class="fas fa-check"></i> Available for selection</span>
    {% else %}
        {% if project.is_waiting(sel) %}
            <a href="{{ url_for('student.cancel_confirmation', sid=sel.id, pid=project.id) }}" class="badge badge-warning">
                <i class="fas fa-times"></i> Cancel request
            </a>
        {% else %}
            <a href="{{ url_for('student.request_confirmation', sid=sel.id, pid=project.id) }}" class="badge badge-primary">
                <i class="fas fa-plus"></i> Request confirmation
            </a>
        {% endif %}
    {% endif %}
{% else %}
   <span class="badge badge-secondary">Not live</span>
{% endif %} 
"""

_bookmarks = \
"""
{% if sel %}
    {% if sel.is_project_bookmarked(project) %}
        <a href="{{ url_for('student.remove_bookmark', sid=sel.id, pid=project.id) }}"
           class="badge badge-primary">
           <i class="fas fa-times"></i> Remove
        </a>
    {% else %}
        <a href="{{ url_for('student.add_bookmark', sid=sel.id, pid=project.id) }}"
           class="badge badge-secondary">
           <i class="fas fa-plus"></i> Add
        </a>
    {% endif %}
{% else %}
   <span class="badge badge-secondary">Not live</span>
{% endif %} 
"""

_selector_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button"
            data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <a class="dropdown-item" href="{{ url_for('student.selector_view_project', sid=sel.id, pid=project.id) }}">
            View project...
        </a>
        {% if is_live and sel %}
            {% if sel.is_project_bookmarked(project) %}
                <a class="dropdown-item" href="{{ url_for('student.remove_bookmark', sid=sel.id, pid=project.id) }}">
                    Remove bookmark
                </a>
            {% else %}
                <a class="dropdown-item" href="{{ url_for('student.add_bookmark', sid=sel.id, pid=project.id) }}">
                    Add bookmark
                </a>
            {% endif %}
            {% set disabled = project.is_available(sel) %}
            {% if not disabled %}
                {% if project.is_waiting(sel) %}
                    <a class="dropdown-item" href="{{ url_for('student.cancel_confirmation', sid=sel.id, pid=project.id) }}">
                        Cancel confirmation
                    </a>
                {% else %}
                    <a class="dropdown-item" href="{{ url_for('student.request_confirmation', sid=sel.id, pid=project.id) }}">
                        Request confirmation
                    </a>
                {% endif %}
            {% else %}
                <a class="dropdown-item disabled">Project unavailable</a>
            {% endif %}
        {% else %}
            <div role="separator" class="dropdown-divider"></div>
            <a class="dropdown-item disabled">Project selection not live</a>
        {% endif %}
    </div>
</div>
"""


_submitter_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button"
            data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <a class="dropdown-item" href="{{ url_for('student.submitter_view_project', sid=sub_id, pid=project.id) }}">
            View project...
        </a>
    </div>
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
            {% if sel %}
                {% set href = url_for('student.add_skill_filter', id=sel.id, skill_id=skill.id) %}
            {% endif %}
            <a {% if href %}href="{{ href }}"{% endif %} class="badge badge-secondary" style="{{ skill.group.make_CSS_style() }}">{%- if skill.group.add_group -%}{{ skill.group.name }}:{% endif %} {{ skill.name }}</a>
        {% endif %}
    {% endif %}
{% endfor %}
"""


_project_group = \
"""
{% if sel %}
    {% set href = url_for('student.add_group_filter', id=sel.id, gid=group.id) %}
{% endif %}
<a {% if href %}href="{{ href }}"{% endif %} class="badge badge-secondary" style="{{ group.make_CSS_style() }}">{{ group.name }}</a>
"""


_not_live = \
"""
<span class="badge badge-secondary">Not live</span>
"""


@cache.memoize()
def _selector_element(sel_id, project_id, is_live):
    sel = db.session.query(SelectingStudent).filter_by(id=sel_id).one() if sel_id is not None else None
    p = db.session.query(LiveProject).filter_by(id=project_id).one()

    base = {'name': '<a href="{url}">{name}</a>' \
                .format(name=p.name, url=url_for('student.selector_view_project', sid=sel.id, pid=p.id)),
            'supervisor': '{name} <a href="mailto:{em}">{em}</a>'.format(name=p.owner.user.name, em=p.owner.user.email),
            'group': render_template_string(_project_group, sel=sel, group=p.group),
            'skills': render_template_string(_project_skills, sel=sel, skills=p.ordered_skills),
            'prefer': render_template_string(_project_prefer, project=p),
            'menu': render_template_string(_selector_menu, sel=sel, project=p, is_live=is_live)}

    if is_live:
        extra_fields = {'meeting': render_template_string(_meeting, sel=sel, project=p),
                        'availability': render_template_string(_status, sel=sel, project=p),
                        'bookmarks': render_template_string(_bookmarks, sel=sel, project=p)}
        base.update(extra_fields)

    return base


@cache.memoize()
def _submitter_element(sub_id, project_id):
    p = db.session.query(LiveProject).filter_by(id=project_id).one()

    return {'name': '<a href="{url}">{name}</a>' \
                .format(name=p.name, url=url_for('student.submitter_view_project', sid=sub_id, pid=p.id)),
            'supervisor': '{name} <a href="mailto:{em}">{em}</a>'.format(name=p.owner.user.name, em=p.owner.user.email),
            'group': render_template_string(_project_group, sel=None, group=p.group),
            'skills': render_template_string(_project_skills, sel=None, skills=p.ordered_skills),
            'prefer': render_template_string(_project_prefer, project=p),
            'menu': render_template_string(_submitter_menu, sub_id=sub_id, project=p)}


def _delete_browsing_cache(owner_id, project_id):
    cache.delete_memoized(_selector_element, owner_id, project_id, True)
    cache.delete_memoized(_selector_element, owner_id, project_id, False)


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


def selector_liveprojects_data(sel_id, is_live, projects):
    data = [_selector_element(sel_id, p.id, is_live) for p in projects]

    return data


def submitter_liveprojects_data(sub_id, projects):
    data = [_submitter_element(sub_id, p.id) for p in projects]

    return data
