#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, url_for
from sqlalchemy.event import listens_for

from ...cache import cache
from ...database import db
from ...models import ConfirmRequest, SelectingStudent, LiveProject, Bookmark, ProjectClassConfig

# language=jinja2
_meeting = \
"""
{% if project.meeting_reqd == project.MEETING_REQUIRED %}
    {% if sel %}
        {% if project.is_confirmed(sel) %}
            <span class="badge bg-primary"><i class="fas fa-check"></i> Confirmed</span>
        {% else %}
            <span class="badge bg-danger"><i class="fas fa-times"></i> Required</span>
        {% endif %}
    {% else %}
        <span class="badge bg-secondary">Not live</span>
    {% endif %}
{% elif project.meeting_reqd == project.MEETING_OPTIONAL %}
    <span class="badge bg-warning text-dark">Optional</span>
{% else %}
    <span class="badge bg-secondary"><i class="fas fa-check"></i> Not required</span>
{% endif %}
"""


# language=jinja2
_status = \
"""
{% if sel %}
    {% if project.is_available(sel) %}
        <span class="badge bg-success"><i class="fas fa-check"></i> Available for selection</span>
    {% else %}
        {% if project.is_waiting(sel) %}
            <a href="{{ url_for('student.cancel_confirmation', sid=sel.id, pid=project.id) }}" class="badge bg-warning text-dark text-decoration-none">
                <i class="fas fa-times"></i> Cancel request
            </a>
        {% else %}
            <a href="{{ url_for('student.request_confirmation', sid=sel.id, pid=project.id) }}" class="badge bg-primary text-decoration-none">
                <i class="fas fa-plus"></i> Request confirmation
            </a>
        {% endif %}
    {% endif %}
{% else %}
   <span class="badge bg-secondary">Not live</span>
{% endif %} 
"""

# language=jinja2
_bookmarks = \
"""
{% if sel %}
    {% if sel.is_project_bookmarked(project) %}
        <a href="{{ url_for('student.remove_bookmark', sid=sel.id, pid=project.id) }}"
           class="badge bg-primary text-decoration-none">
           <i class="fas fa-times"></i> Remove
        </a>
    {% else %}
        <a href="{{ url_for('student.add_bookmark', sid=sel.id, pid=project.id) }}"
           class="badge bg-secondary text-decoration-none">
           <i class="fas fa-plus"></i> Add
        </a>
    {% endif %}
{% else %}
   <span class="badge bg-secondary">Not live</span>
{% endif %} 
"""

# language=jinja2
_selector_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('student.selector_view_project', sid=sel.id, pid=project.id) }}">
            <i class="fas fa-eye fa-fw"></i> View project...
        </a>
        {% if is_live and sel %}
            {% if sel.is_project_bookmarked(project) %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('student.remove_bookmark', sid=sel.id, pid=project.id) }}">
                    <i class="fas fa-fw fa-trash"></i> Remove bookmark
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('student.add_bookmark', sid=sel.id, pid=project.id) }}">
                    <i class="fas fa-fw fa-plus"></i> Add bookmark
                </a>
            {% endif %}
            {% if config.uses_selection %}
                {% set disabled = project.is_available(sel) %}
                {% if not disabled %}
                    {% if project.is_waiting(sel) %}
                        <a class="dropdown-item d-flex gap-2" href="{{ url_for('student.cancel_confirmation', sid=sel.id, pid=project.id) }}">
                            <i class="fas fa-times fa-fw"></i> Cancel confirmation
                        </a>
                    {% else %}
                        <a class="dropdown-item d-flex gap-2" href="{{ url_for('student.request_confirmation', sid=sel.id, pid=project.id) }}">
                            <i class="fas fa-check fa-fw"></i> 'Request confirmation
                        </a>
                    {% endif %}
                {% else %}
                    <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-ban fa-fw"></i> Project unavailable</a>
                {% endif %}
            {% endif %}
        {% else %}
            <div role="separator" class="dropdown-divider"></div>
            <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-ban fa-fw"></i> Project selection not live</a>
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_submitter_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('student.submitter_view_project', sid=sub_id, pid=project.id) }}">
            <i class="fas fa-eye fa-fw"></i> View project...
        </a>
    </div>
</div>
"""


# language=jinja2
_project_prefer = \
"""
{% for programme in project.programmes %}
    {% if programme.active %}
        {{ programme.label|safe }}
    {% endif %}
{% endfor %}
"""

# language=jinja2
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
            <a {% if href %}href="{{ href }}"{% endif %} class="badge bg-secondary text-decoration-none" style="{{ skill.group.make_CSS_style() }}">{%- if skill.group.add_group -%}{{ skill.group.name }}:{% endif %} {{ skill.name }}</a>
        {% endif %}
    {% endif %}
{% endfor %}
"""


# language=jinja2
_project_group = \
"""
{% set ns = namespace(affiliation=false) %}
{% if project.group and config.advertise_research_group %}
    {% set group = project.group %}
    {% if sel %}
        {% set href = url_for('student.add_group_filter', id=sel.id, gid=group.id) %}
    {% endif %}
    <a {% if href %}href="{{ href }}"{% endif %} class="badge bg-secondary text-decoration-none" style="{{ group.make_CSS_style() }}">{{ group.name }}</a>
{% endif %}
{% for tag in project.forced_group_tags %}
    {{ tag.make_label()|safe }}
    {% set ns.affiliation = true %}
{% endfor %}
{% if not ns.affiliation %}
    <span class="badge bg-warning text-dark">No affiliations</span>
{% endif %}
"""


# language=jinja2
_not_live = \
"""
<span class="badge bg-secondary">Not live</span>
"""


@cache.memoize()
def _selector_element(sel_id, project_id, is_live):
    sel: SelectingStudent = db.session.query(SelectingStudent).filter_by(id=sel_id).one() if sel_id is not None else None
    p: LiveProject = db.session.query(LiveProject).filter_by(id=project_id).one()

    config: ProjectClassConfig = p.config

    base = {'name': '<a class="text-decoration-none" '
                    'href="{url}">{name}</a>'.format(name=p.name,
                                                     url=url_for('student.selector_view_project', sid=sel.id,
                                                                 pid=p.id)),
            'supervisor': '{name} <a class="text-decoration-none" '
                          'href="mailto:{em}">{em}</a>'.format(name=p.owner.user.name, em=p.owner.user.email),
            'group': render_template_string(_project_group, sel=sel, project=p, config=config),
            'skills': render_template_string(_project_skills, sel=sel, skills=p.ordered_skills),
            'prefer': render_template_string(_project_prefer, project=p),
            'menu': render_template_string(_selector_menu, sel=sel, project=p, is_live=is_live, config=config)}

    if is_live:
        extra_fields = {'meeting': render_template_string(_meeting, sel=sel, project=p),
                        'availability': render_template_string(_status, sel=sel, project=p),
                        'bookmarks': render_template_string(_bookmarks, sel=sel, project=p)}
        base.update(extra_fields)

    return base


@cache.memoize()
def _submitter_element(sub_id, project_id):
    p: LiveProject = db.session.query(LiveProject).filter_by(id=project_id).one()

    config: ProjectClassConfig = p.config

    return {'name': '<a class="text-decoration-none" href="{url}">{name}</a>' \
                .format(name=p.name, url=url_for('student.submitter_view_project', sid=sub_id, pid=p.id)),
            'supervisor': '{name} <a class="text-decoration-none" href="mailto:{em}">{em}</a>'.format(name=p.owner.user.name, em=p.owner.user.email),
            'group': render_template_string(_project_group, sel=None, project=p, config=config),
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
    if isinstance(projects, list):
        if len(projects) > 0:
            if isinstance(projects[0], int):
                return [_selector_element(sel_id, pid, is_live) for pid in projects]
            else:
                return [_selector_element(sel_id, p.id, is_live) for p in projects]

    else:
        if isinstance(projects, int):
            return [_selector_element(sel_id, projects, is_live)]
        else:
            return [_selector_element(sel_id, projects.id, is_live)]

    return []


def submitter_liveprojects_data(sub_id, projects):
    if isinstance(projects, list):
        if len(projects) > 0:
            if isinstance(projects[0], int):
                return [_submitter_element(sub_id, pid) for pid in projects]
            else:
                return [_submitter_element(sub_id, p.id) for p in projects]

    else:
        if isinstance(projects, int):
            return [_submitter_element(sub_id, projects)]
        else:
            return [_submitter_element(sub_id, projects.id)]

    return []
