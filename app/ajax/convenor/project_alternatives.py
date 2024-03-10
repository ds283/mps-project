#
# Created by David Seery on 08/03/2024.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List, Optional

from flask import current_app, render_template, get_template_attribute
from jinja2 import Template, Environment

from ...models import ProjectAlternative, Project

# language=jinja2
_project = """
<a class="text-decoration-none" href="{{ url_for('faculty.project_preview', id=proj.id, text='project alternatives list', url=url_for('convenor.edit_project_alternatives', proj_id=proj.id, url=url, text=text)) }}">{{ proj.name }}</a>
{% set reciprocal = alt.get_reciprocal() %}
{% set has_reciprocal = reciprocal is not none %}
{% if not has_reciprocal %}
    <div class="mt-1 small d-flex flex-row gap-2 justify-content-left align-items-center">
        <div class="text-danger"><i class="fas fa-exclamation-circle me-1"></i> Reciprocal not present</div>
        <a class="btn btn-xs btn-outline-danger" href="{{ url_for('convenor.copy_project_alternative_reciprocal', alt_id=alt.id) }}">Copy</a>
    </div>
{% else %}
    <div class="mt-1 small d-flex flex-row gap-2 justify-content-left align-items-center">
        <div class="text-success">
            <i class="fas fa-check-circle me-1"></i> Reciprocal present
            {% if reciprocal.priority != alt.priority %}
                (priority {{ reciprocal.priority }})
            {% endif %}
        </div>
    </div>
{% endif %}
"""

# language=jinja2
_priority = """
{{ alt.priority }}
"""

# langauge=jinja2
_supervision = """
{% if not proj.generic %}
    {% if proj.owner is not none %}
        <i class="fas fa-user-circle"></i> {{ proj.owner.user.name }}
    {% else %}
        <span class="badge bg-danger text-white">MISSING PROJECT OWNER</span>
    {% endif %}
{% else %}
    <div class="small text-muted text-uppercase mb-2">Supervisor Pool</div>
    {% for fd in proj.supervisors %}
        <div class="d-flex flex-row gap-1 justify-content-left align-items-center">
            <i class="fas fa-user-circle"></i>
            <span>{{ fd.user.name }}</span>
        </div>
    {% endfor %}
{% endif %}
"""

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_project_alternative', alt_id=alt.id, url=url_for('convenor.edit_project_alternatives', proj_id=alt.parent_id, url=url, text=text)) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.delete_project_alternative', alt_id=alt.id) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    </div>
</div>
"""


def _build_project_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_project)


def _build_priority_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_priority)


def _build_supervision_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_supervision)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def project_alternatives(alternatives: List[ProjectAlternative], url: Optional[str] = None, text: Optional[str] = None):
    project_templ: Template = _build_project_templ()
    priority_templ: Template = _build_priority_templ()
    supervision_templ: Template = _build_supervision_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "project": render_template(project_templ, alt=alt, proj=alt.alternative, url=url, text=text),
            "priority": render_template(priority_templ, alt=alt),
            "supervision": render_template(supervision_templ, proj=alt.alternative),
            "menu": render_template(menu_templ, alt=alt, url=url, text=text),
        }
        for alt in alternatives
    ]

    return data


# language=jinja2
_alternative = """
<a class="text-decoration-none" href="{{ url_for('faculty.project_preview', id=alt_proj.id, text='new alternative view', url=url_for('convenor.new_project_alternative', proj_id=parent.id, url=url)) }}">{{ alt_proj.name }}</a>
"""


# language=jinja2
_owner = """
{% if not alt_proj.generic and alt_proj.owner is not none %}
    <a class="text-decoration-none" href="mailto:{{ alt_proj.owner.user.email }}">{{ alt_proj.owner.user.name }}</a>
    {% if alt_proj.group %}{{ simple_label(alt_proj.group.make_label()) }}{% endif %}
{% else %}
    <span class="badge bg-info">Generic</span>
{% endif %}
"""


# language=jinja2
_alt_actions = """
<div class="d-flex flex-row justify-content-end">
    <a href="{{ url_for('convenor.create_project_alternative', proj_id=parent.id, alt_proj_id=alt_proj.id, url=url) }}"
       class="btn btn-sm btn-outline-primary">
       <i class="fas fa-plus"></i> Add alternative
    </a>
</div>
"""


def _build_alternative_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_alternative)


def _build_owner_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_owner)


def _build_alt_actions_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_alt_actions)


def new_project_alternative(projects: List[Project], parent: Project, url: Optional[str] = None):
    alternative_templ: Template = _build_alternative_templ()
    owner_templ: Template = _build_owner_templ()
    alt_actions_templ: Template = _build_alt_actions_templ()

    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [
        {
            "project": render_template(alternative_templ, alt_proj=proj, parent=parent, url=url),
            "owner": render_template(owner_templ, alt_proj=proj, simple_label=simple_label),
            "actions": render_template(alt_actions_templ, alt_proj=proj, parent=parent, url=url)
        }
        for proj in projects
    ]

    return data
