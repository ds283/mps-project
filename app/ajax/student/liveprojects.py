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

from ...models import SelectingStudent, LiveProject, ProjectClassConfig, SubmittingStudent

# language=jinja2
_meeting = """
{% if not project.generic and project.owner is not none %}    
    {% if project.meeting_reqd == project.MEETING_REQUIRED %}
        {% if sel %}
            {% if project.is_confirmed(sel) %}
                <span class="text-success"><i class="fas fa-check-circle"></i> Confirmed</span>
            {% else %}
                <span class="text-danger"><i class="fas fa-exclamation-circle"></i> Required</span>
            {% endif %}
        {% else %}
           <span class="text-secondary"><i class="fas fa-ban"></i> Not live</span>
        {% endif %}
    {% elif project.meeting_reqd == project.MEETING_OPTIONAL %}
        <span class="text-secondary"><i class="fas fa-info-circle"></i> Optional</span>
    {% else %}
        <span class="text-secondary"><i class="fas fa-info-circle"></i> Not required</span>
    {% endif %}
{% else %}
    <span class="text-secondary"><i class="fas fa-info-circle"></i> Not required</span>
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
                {% set available = project.is_available(sel) %}
                {% if not available %}
                    {% if project.is_waiting(sel) %}
                        <a class="dropdown-item d-flex gap-2" href="{{ url_for('student.cancel_confirmation', sid=sel.id, pid=project.id) }}">
                            <i class="fas fa-times fa-fw"></i> Cancel confirmation
                        </a>
                    {% else %}
                        <a class="dropdown-item d-flex gap-2" href="{{ url_for('student.request_confirmation', sid=sel.id, pid=project.id) }}">
                            <i class="fas fa-check fa-fw"></i> Request confirmation
                        </a>
                    {% endif %}
                {% else %}
                    <a class="dropdown-item d-flex gap-2 disabled"><i class="fas fa-check fa-fw"></i> Available to select</a>
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


# language=jinja2
_owner = """
{% if project.generic %}
    <div class="text-primary">Generic</div>
{% else %}
    {% if project.owner is not none %}
        <div><a class="text-decoration-none link-primary" href="mailto:{{ project.owner.user.email }}">{{ project.owner.user.name }}</a></div>
    {% else %}
        <div class="text-danger"><i class="fas fa-exclamation-triangle"></i> Project owner missing</div>
    {% endif %}
{% endif %}
"""


# language=jinja2
_name = """
{% if sel %}
    <div class="mb-1"><a class="link-secondary" href="{{ url_for("student.selector_view_project", sid=sel.id, pid=project.id) }}"><strong>{{ project.name }}</strong></a></div>
{% else %}
    <div class="mb-1"><strong>{{ project.name }}</strong></div>
{% endif %}
{% if is_live and sel and config.uses_selection %}
    {% if project.is_available(sel) %}
        <div class="text-success small mb-1"><i class="fas fa-check-circle"></i> Available to select</div>
    {% else %}
        {% if project.is_waiting(sel) %}
            <div><a href="{{ url_for('student.cancel_confirmation', sid=sel.id, pid=project.id) }}" class="btn btn-xs btn-outline-danger">
                <i class="fas fa-trash"></i> Cancel confirmation request
            </a></div>
        {% else %}
            <div><a href="{{ url_for('student.request_confirmation', sid=sel.id, pid=project.id) }}" class="btn btn-xs btn-outline-primary">
                <i class="fas fa-plus"></i> Request confirmation
            </a></div>
        {% endif %}
    {% endif %}
    {% if sel.is_project_bookmarked(project) %}
        <div><a href="{{ url_for('student.remove_bookmark', sid=sel.id, pid=project.id) }}"
           class="btn btn-xs btn-outline-danger">
           <i class="fas fa-trash"></i> Remove bookmark
        </a></div>
    {% else %}
        <div><a href="{{ url_for('student.add_bookmark', sid=sel.id, pid=project.id) }}"
           class="btn btn-xs btn-outline-success">
           <i class="fas fa-plus-circle"></i> Add bookmark
        </a></div>
    {% endif %}
{% endif %}
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_owner_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_owner)


def _build_group_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_project_group)


def _build_prefer_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_project_prefer)


def _build_skills_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_project_skills)


def _build_meeting_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_meeting)


def _build_submitter_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_submitter_menu)


def _build_selector_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_selector_menu)


def selector_liveprojects_data(sel: SelectingStudent, is_live: bool, projects: List[LiveProject]):
    if hasattr(projects, "len") and len(projects) == 0:
        return []

    simple_label = get_template_attribute("labels.html", "simple_label")

    name_templ: Template = _build_name_templ()
    owner_templ: Template = _build_owner_templ()
    group_templ: Template = _build_group_templ()
    skills_templ: Template = _build_skills_templ()
    prefer_templ: Template = _build_prefer_templ()
    menu_templ: Template = _build_selector_menu_templ()

    meeting_templ: Template = _build_meeting_templ()

    config: ProjectClassConfig = sel.config

    def _process(p: LiveProject, is_live: bool):
        base = {
            "name": render_template(name_templ, project=p, is_live=is_live, sel=sel, config=config),
            "supervisor": render_template(owner_templ, project=p),
            "group": render_template(group_templ, sel=sel, project=p, config=config, simple_label=simple_label),
            "skills": render_template(skills_templ, sel=sel, skills=p.ordered_skills, simple_label=simple_label),
            "prefer": render_template(prefer_templ, project=p, simple_label=simple_label),
            "menu": render_template(menu_templ, sel=sel, project=p, is_live=is_live, config=config),
        }

        if is_live:
            extra_fields = {
                "meeting": render_template(meeting_templ, sel=sel, project=p),
            }
            base.update(extra_fields)

        return base

    return [_process(p, is_live) for p in projects]


def submitter_liveprojects_data(sub: SubmittingStudent, projects: List[LiveProject]):
    if hasattr(projects, "len") and len(projects) == 0:
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
