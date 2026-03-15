#
# Created by David Seery on 12/12/2022.
# Copyright (c) 2022 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, get_template_attribute, render_template
from jinja2 import Environment, Template

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_project_tag_group', gid=group.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit details...
        </a>
        {% if group.active %}
            {% if not group.default %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_project_tag_group', gid=group.id) }}">

< i


class ="fas fa-times-circle fa-fw" > < / i > Make inactive
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-w disabled">

< i


class ="fas fa-times-circle fa-fw" > < / i > Make inactive
                </a>
            {% endif %}
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_project_tag_group', gid=group.id) }}">

< i


class ="fas fa-check-circle fa-fw" > < / i > Make active
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
_include_name = """
{% if g.add_group %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Yes</span>
{% else %}
    <span class="badge bg-secondary"><i class="fas fa-times"></i> No</span>
{% endif %}
"""


# language=jinja2
_name = """
<div>{{ g.name }}</div>
<div class="mt-1 d-flex flex-row flex-wrap justify-content-start align-items-center gap-2 small">
    {% if g.default %}
        <span class="badge bg-success">Default</span>
    {% endif %}
</div>
<div class="mt-1 small d-flex flex-row flex-wrap justify-content-start align-items-start gap-2">
    {% for tenant in g.tenants %}
        {{ simple_label(tenant.make_label(tenant.name)) }}
    {% endfor %}
</div>
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_active_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_active)


def _build_include_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_include_name)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def tag_groups_data(groups):
    simple_label = get_template_attribute("labels.html", "simple_label")

    name_templ: Template = _build_name_templ()
    active_templ: Template = _build_active_templ()
    include_name_templ: Template = _build_include_name_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "name": render_template(name_templ, g=g, simple_label=simple_label),
            "active": render_template(active_templ, g=g),
            "include": render_template(include_name_templ, g=g),
            "menu": render_template(menu_templ, group=g),
        }
        for g in groups
    ]

    return data
