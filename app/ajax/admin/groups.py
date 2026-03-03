#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
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
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_group', id=group.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit details...
        </a>

        {% if group.active %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_group', id=group.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_group', id=group.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make active
            </a>
        {% endif %}
    </div>
</div>
"""

# language=jinja2
_active = """
{% if g.active %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""

# language=jinja2
_colour = """
{% if g.colour %}
    {{ simple_label(g.make_label(g.colour)) }}
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""

# language=jinja2
_website = """
{% if g.website %}
    <a class="text-decoration-none small" href="{{ g.website }}">{{ g.website }}</a>
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""

# language=jinja2
_abbreviation = """
<div>{{ g.abbreviation }}</div>
<div class="mt-1 small d-flex flex-row flex-wrap justify-content-start align-items-start gap-2">
    {% for tenant in g.tenants %}
        {{ simple_label(tenant.make_label(tenant.name)) }}
    {% endfor %}
</div>
"""

# language=jinja2
_name = """
{{ g.name }}
"""


def _build_abbreviation_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_abbreviation)


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_active_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_active)


def _build_colour_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_colour)


def _build_website_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_website)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def groups_data(groups):
    simple_label = get_template_attribute("labels.html", "simple_label")

    abbreviation_templ: Template = _build_abbreviation_templ()
    name_templ: Template = _build_name_templ()
    active_templ: Template = _build_active_templ()
    colour_templ: Template = _build_colour_templ()
    website_templ: Template = _build_website_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "abbrv": render_template(abbreviation_templ, g=g, simple_label=simple_label),
            "active": render_template(active_templ, g=g),
            "name": render_template(name_templ, g=g),
            "colour": render_template(colour_templ, g=g, simple_label=simple_label),
            "website": render_template(website_templ, g=g),
            "menu": render_template(menu_templ, group=g),
        }
        for g in groups
    ]

    return data
