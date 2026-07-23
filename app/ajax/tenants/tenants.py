#
# Created by David Seery on 02/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import (
    current_app,
    get_template_attribute,
    render_template,
)
from jinja2 import Environment, Template


# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('tenants.edit_tenant', id=t.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit&hellip;
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('tenants.email_templates', tenant_id=t.id, url=url, text=text) }}">
            <i class="fas fa-envelope fa-fw"></i> Email templates&hellip;
        </a>
        <div class="dropdown-divider"></div>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('tenants.ai_calibrations', tenant_id=t.id) }}">
            <i class="fas fa-ruler-combined fa-fw"></i> AI calibrations&hellip;
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('tenants.recalculate_ai_concern', tenant_id=t.id) }}">
            <i class="fas fa-sync fa-fw"></i> Recalculate AI concern&hellip;
        </a>
        <div class="dropdown-divider"></div>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('tenants.export_marking_data', tenant_id=t.id) }}">
            <i class="fas fa-file-excel fa-fw"></i> Export marking data&hellip;
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
{% if t.in_2026_ATAS_campaign %}
    <div class="mt-2 d-flex flex-row flex-wrap justify-content-start align-items-start gap-2 small">
        {% if t.in_2026_ATAS_campaign %}
            <span class="badge bg-info">2026 ATAS campaign</span>
        {% endif %}
    </div>
{% endif %}
"""

# language=jinja2
_calibration = """
{% set n = t.ai_calibrations | length %}
{% if n > 0 %}
    <span class="badge bg-success">
        <i class="fas fa-check-circle fa-fw"></i>
        {{ n }} calibration{{ 's' if n != 1 else '' }}
    </span>
{% else %}
    <span class="badge bg-secondary">Not calibrated</span>
{% endif %}
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_colour_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_colour)


def _build_calibration_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_calibration)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def tenants_data(url, text, tenants):
    """
    Build the JSON payload for the tenants DataTable.
    """
    simple_label = get_template_attribute("labels.html", "simple_label")

    name_templ: Template = _build_name_templ()
    colour_templ: Template = _build_colour_templ()
    calibration_templ: Template = _build_calibration_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "name": render_template(name_templ, t=t),
            "colour": render_template(colour_templ, t=t, simple_label=simple_label),
            "calibration": render_template(calibration_templ, t=t),
            "menu": render_template(menu_templ, t=t, url=url, text=text),
        }
        for t in tenants
    ]

    return data
