#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import List

from flask import url_for, get_template_attribute, current_app, render_template
from jinja2 import Template, Environment

from ...cache import cache
from ...models import SelectingStudent, LiveProject, ProjectClassConfig, SubmittingStudent

# language=jinja2
_meeting = """
{% if not project.generic and project.owner is not none %}    
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
{% else %}
    <span class="badge bg-secondary"><i class="fas fa-check"></i> Not required</span>
{% endif %}
"""


# language=jinja2
_status = """
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
_bookmarks = """
{% if sel %}
    {% if sel.is_project_bookmarked(project) %}
        <a href="{{ url_for('student.remove_bookmark', sid=sel.id, pid=project.id) }}"
           class="badge bg-primary text-decoration-none text-light">
           <i class="fas fa-times"></i> Remove
        </a>
    {% else %}
        <a href="{{ url_for('student.add_bookmark', sid=sel.id, pid=project.id) }}"
           class="badge bg-secondary text-decoration-none text-light">
           <i class="fas fa-plus"></i> Add
        </a>
    {% endif %}
{% else %}
   <span class="badge bg-secondary">Not live</span>
{% endif %} 
"""

# language=jinja2
_selector_menu = """
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
_submitter_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('student.submitter_view_project', sid=sub.id, pid=project.id) }}">
            <i class="fas fa-eye fa-fw"></i> View project...
        </a>
    </div>
</div>
"""


# language=jinja2
_project_prefer = """
{% for programme in project.programmes %}
    {% if programme.active %}
        {{ simple_label(programme.label) }}
    {% endif %}
{% endfor %}
"""

# language=jinja2
_project_skills = """
{% for skill in skills %}
    {% if skill.is_active %}
        {% if skill.group is none %}
            {{ simple_label(skill.make_label()) }}
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
_project_group = """
{% set ns = namespace(affiliation=false) %}
{% if project.group and config.advertise_research_group %}
    {% set group = project.group %}
    {% if sel %}
        {% set href = url_for('student.add_group_filter', id=sel.id, gid=group.id) %}
    {% endif %}
    <a {% if href %}href="{{ href }}"{% endif %} class="badge bg-secondary text-decoration-none" style="{{ group.make_CSS_style() }}">{{ group.name }}</a>
    {% set ns.affiliation = true %}
{% endif %}
{% for tag in project.forced_group_tags %}
    {{ simple_label(tag.make_label()) }}
    {% set ns.affiliation = true %}
{% endfor %}
{% if not ns.affiliation %}
    <span class="badge bg-warning text-dark">No affiliations</span>
{% endif %}
"""


# language=jinja2
_not_live = """
<span class="badge bg-secondary">Not live</span>
"""


# langauge=jinja2
_owner = """
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


@cache.memoize()
def _build_owner_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_owner)


@cache.memoize()
def _build_group_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_project_group)


@cache.memoize()
def _build_prefer_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_project_prefer)


@cache.memoize()
def _build_skills_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_project_skills)


@cache.memoize()
def _build_meeting_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_meeting)


@cache.memoize()
def _build_status_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_status)


@cache.memoize()
def _build_bookmarks_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_bookmarks)


@cache.memoize()
def _build_submitter_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_submitter_menu)


@cache.memoize()
def _build_selector_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_selector_menu)


def selector_liveprojects_data(sel: SelectingStudent, is_live: bool, projects: List[LiveProject]):
    if hasattr(projects, 'len') and len(projects) == 0:
        return []

    simple_label = get_template_attribute("labels.html", "simple_label")

    owner_templ: Template = _build_owner_templ()
    group_templ: Template = _build_group_templ()
    skills_templ: Template = _build_skills_templ()
    prefer_templ: Template = _build_prefer_templ()
    menu_templ: Template = _build_selector_menu_templ()

    meeting_templ: Template = _build_meeting_templ()
    status_templ: Template = _build_status_templ()
    bookmarks_templ: Template = _build_bookmarks_templ()

    config: ProjectClassConfig = sel.config

    def _process(p: LiveProject, is_live: bool):
        base = {
            "name": '<a class="text-decoration-none" '
            'href="{url}">{name}</a>'.format(name=p.name, url=url_for("student.selector_view_project", sid=sel.id, pid=p.id)),
            "supervisor": render_template(owner_templ, project=p),
            "group": render_template(group_templ, sel=sel, project=p, config=config, simple_label=simple_label),
            "skills": render_template(skills_templ, sel=sel, skills=p.ordered_skills, simple_label=simple_label),
            "prefer": render_template(prefer_templ, project=p, simple_label=simple_label),
            "menu": render_template(menu_templ, sel=sel, project=p, is_live=is_live, config=config),
        }

        if is_live:
            extra_fields = {
                "meeting": render_template(meeting_templ, sel=sel, project=p),
                "availability": render_template(status_templ, sel=sel, project=p),
                "bookmarks": render_template(bookmarks_templ, sel=sel, project=p),
            }
            base.update(extra_fields)

        return base

    return [_process(p, is_live) for p in projects]


def submitter_liveprojects_data(sub: SubmittingStudent, projects: List[LiveProject]):
    if hasattr(projects, 'len') and len(projects) == 0:
        return []

    simple_label = get_template_attribute("labels.html", "simple_label")

    owner_templ: Template = _build_owner_templ()
    group_templ: Template = _build_group_templ()
    skills_templ: Template = _build_skills_templ()
    prefer_templ: Template = _build_prefer_templ()
    menu_templ: Template = _build_submitter_menu_templ()

    config: ProjectClassConfig = sub.config

    def _process(p: LiveProject):
        return {
            "name": '<a class="text-decoration-none" href="{url}">{name}</a>'.format(
                name=p.name, url=url_for("student.submitter_view_project", sid=sub.id, pid=p.id)
            ),
            "supervisor": render_template(owner_templ, project=p),
            "group": render_template(group_templ, sel=None, project=p, config=config, simple_label=simple_label),
            "skills": render_template(skills_templ, sel=None, skills=p.ordered_skills, simple_label=simple_label),
            "prefer": render_template(prefer_templ, project=p, simple_label=simple_label),
            "menu": render_template(menu_templ, sub=sub, project=p),
        }

    return [_process(p) for p in projects]
