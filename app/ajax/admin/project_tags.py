#
# Created by David Seery on 12/12/2022.
# Copyright (c) 2022 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import get_template_attribute, current_app, render_template
from jinja2 import Template, Environment

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_project_tag', tid=tag.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit details...
        </a>
        {% if tag.group is not none and tag.group.active %}
            {% if tag.active %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_project_tag', tid=tag.id) }}">
                    <i class="fas fa-wrench fa-fw"></i> Make inactive
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_project_tag', tid=tag.id) }}">
                    <i class="fas fa-wrench fa-fw"></i> Make active
                </a>
            {% endif %}
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled">Parent disabled</a>
        {% endif %}
    </ul>
</div>
"""


# language=jinja2
_active = """
{% if t.active %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""


# language=jinja2
_group = """
{% if t.group %}
    <span class="badge bg-secondary">{{ t.group.name }}</span>
{% else %}
    <span class="badge bg-danger">None</span>
{% endif %}
"""


# language=jinja2
_colour = """
{% if t.colour %}
    {{ simple_label(t.make_label(text=t.colour)) }}
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}    
"""


# language=jinja2
_uses = """
{% set uses = t.uses %}
<div class="d-flex flex-column justify-content-start align-items-start gap-2 small">
{% for u in uses %}
    <span class="text-secondary">{{ u }}: {{ uses[u] }}</span>
{% endfor %}   
</div>
"""


def _build_colour_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_colour)


def _build_group_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_group)


def _build_uses_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_uses)


def _build_active_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_active)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def tags_data(tags):
    simple_label = get_template_attribute("labels.html", "simple_label")

    colour_templ: Template = _build_colour_templ()
    group_templ: Template = _build_group_templ()
    uses_templ: Template = _build_uses_templ()
    active_templ: Template = _build_active_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "name": t.name,
            "colour": render_template(colour_templ, t=t, simple_label=simple_label),
            "group": render_template(group_templ, t=t),
            "uses": render_template(uses_templ, t=t),
            "active": render_template(active_templ, t=t),
            "menu": render_template(menu_templ, tag=t),
        }
        for t in tags
    ]

    return data
