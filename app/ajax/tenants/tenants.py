#
# Created by David Seery on 02/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, get_template_attribute, current_app, render_template
from jinja2 import Template, Environment

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('tenants.edit_tenant', id=t.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit...
        </a>
    </div>
</div>
"""

# language=jinja2
_colour = """
{% if t.colour %}
    {{ simple_label(t.make_label(t.colour)) }}
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""

# language=jinja2
_name = """
<div>{{ t.name }}</div>
{% if t.force_ATAS_flag or t.in_2026_ATAS_campaign %}
    <div class="mt-2 d-flex flex-row flex-wrap justify-content-start align-items-start gap-2 small">
        {% if t.force_ATAS_flag %}
            <span class="badge bg-info">Force ATAS</span>
        {% endif %}
        {% if t.in_2026_ATAS_campaign %}
            <span class="badge bg-info">2026 ATAS campaign</span>
        {% endif %}
    </div>
{% endif %}
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_colour_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_colour)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def tenants_data(tenants):
    """
    Build the JSON payload for the tenants DataTable.
    """
    simple_label = get_template_attribute("labels.html", "simple_label")

    name_templ: Template = _build_name_templ()
    colour_templ: Template = _build_colour_templ()
    menu_templ: Template = _build_menu_templ()

    data = [{
            'name': render_template(name_templ, t=t),
            'colour': render_template(colour_templ, t=t, simple_label=simple_label),
            'menu': render_template(menu_templ, t=t),
        } for t in tenants]

    return data
