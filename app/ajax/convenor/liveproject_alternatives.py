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

from ...models import LiveProjectAlternative, LiveProject

# language=jinja2
_project = """
<a class="text-decoration-none" href="{{ url_for('faculty.live_project', pid=lp.id, text='LiveProject alternatives list', url=url_for('convenor.edit_liveproject_alternatives', lp_id=lp.id, url=url, text=text)) }}">{{ lp.name }}</a>
{% if lp.hidden %}
    <div>
        <span class="badge bg-danger"><i class="fas fa-eye-slash"></i> HIDDEN</span>
    </div>
{% endif %}
{% if not alt.in_library %}
    <div class="mt-1 small text-danger">
        <i class="fas fa-exclamation-circle me-1"></i> Not in library
    </div>
{% endif %}
"""

# language=jinja2
_priority = """
{{ alt.priority }}
"""

# langauge=jinja2
_supervision = """
{% if not lp.generic %}
    {% if lp.owner is not none %}
        <i class="fas fa-user-circle"></i> {{ lp.owner.user.name }}
    {% else %}
        <span class="badge bg-danger text-white">MISSING PROJECT OWNER</span>
    {% endif %}
{% else %}
    <div class="small text-muted text-uppercase mb-2">Supervisor Pool</div>
    {% for fd in lp.supervisors %}
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
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_liveproject_alternative', alt_id=alt.id, url=url_for('convenor.edit_liveproject_alternatives', lp_id=alt.parent_id, url=url, text=text)) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.delete_liveproject_alternative', alt_id=alt.id) }}">
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


def liveproject_alternatives(alternatives: List[LiveProjectAlternative], url: Optional[str] = None, text: Optional[str] = None):
    project_templ: Template = _build_project_templ()
    priority_templ: Template = _build_priority_templ()
    supervision_templ: Template = _build_supervision_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "project": render_template(project_templ, alt=alt, lp=alt.alternative, url=url, text=text),
            "priority": render_template(priority_templ, alt=alt),
            "supervision": render_template(supervision_templ, lp=alt.alternative),
            "menu": render_template(menu_templ, alt=alt, url=url, text=text),
        }
        for alt in alternatives
    ]

    return data


# language=jinja2
_alternative = """
<a class="text-decoration-none" href="{{ url_for('faculty.live_project', pid=alt_lp.id, text='new alternative view', url=url_for('convenor.new_liveproject_alternative', lp_id=parent.id, url=url)) }}">{{ alt_lp.name }}</a>
{% if alt_lp.hidden %}
    <div>
        <span class="badge bg-danger"><i class="fas fa-eye-slash"></i> HIDDEN</span>
    </div>
{% endif %}
"""


# language=jinja2
_owner = """
{% if not alt_lp.generic and alt_lp.owner is not none %}
    <a class="text-decoration-none" href="mailto:{{ alt_lp.owner.user.email }}">{{ alt_lp.owner.user.name }}</a>
    {% if alt_lp.group %}{{ simple_label(alt_lp.group.make_label()) }}{% endif %}
{% else %}
    <span class="badge bg-info">Generic</span>
{% endif %}
"""


# language=jinja2
_alt_actions = """
<div class="d-flex flex-row justify-content-end">
    <a href="{{ url_for('convenor.create_liveproject_alternative', lp_id=parent.id, alt_lp_id=alt_lp.id, url=url) }}"
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


def new_liveproject_alternative(projects: List[LiveProject], parent: LiveProject, url: Optional[str] = None):
    alternative_templ: Template = _build_alternative_templ()
    owner_templ: Template = _build_owner_templ()
    alt_actions_templ: Template = _build_alt_actions_templ()

    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [
        {
            "project": render_template(alternative_templ, alt_lp=alt, parent=parent, url=url),
            "owner": render_template(owner_templ, alt_lp=alt, simple_label=simple_label),
            "actions": render_template(alt_actions_templ, alt_lp=alt, parent=parent, url=url)
        }
        for alt in projects
    ]

    return data
