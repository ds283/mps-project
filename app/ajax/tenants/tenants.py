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
    render_template_string,
)
from jinja2 import Environment, Template

from ...models import ProjectClass

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
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('tenants.calibrate_ai_concern', tenant_id=t.id) }}">
            <i class="fas fa-ruler-combined fa-fw"></i> AI calibration&hellip;
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('tenants.recalculate_ai_concern', tenant_id=t.id) }}">
            <i class="fas fa-sync fa-fw"></i> Recalculate AI concern&hellip;
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
{% set cal = t.ai_calibration_data %}
{% if cal %}
    <div class="d-flex flex-column gap-1 small">
        <div><span class="badge bg-success"><i class="fas fa-check-circle fa-fw"></i> Calibrated</span></div>
        <div class="text-muted">
            {% set ts = cal.calibrated_at %}
            {% if ts %}{{ ts[:10] }}{% endif %}
            &nbsp;&middot;&nbsp; {{ cal.n_samples }} samples
        </div>
        {% if cal.included_years %}
        <div class="d-flex flex-wrap gap-1">
            {% for yr in cal.included_years %}
                <span class="badge bg-secondary" style="font-size:0.7em">{{ yr }}</span>
            {% endfor %}
        </div>
        {% endif %}
        {% if included_pclass_names.get(t.id) %}
        <div class="text-muted" style="font-size:0.8em">
            {{ included_pclass_names[t.id] | join(', ') }}
        </div>
        {% endif %}
    </div>
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

    # Pre-resolve project class names for each tenant's calibration so the
    # Jinja2 template does not need to issue per-row DB queries.
    tenant_ids = [t.id for t in tenants]
    pclasses = ProjectClass.query.filter(ProjectClass.tenant_id.in_(tenant_ids)).all()
    pclass_by_id = {p.id: p.name for p in pclasses}

    # Build {tenant_id: [pclass_name, ...]} for each tenant's calibration data.
    included_pclass_names: dict[int, list[str]] = {}
    for t in tenants:
        cal = t.ai_calibration_data
        if cal and cal.get("included_pclass_ids"):
            included_pclass_names[t.id] = [
                pclass_by_id[pid] for pid in cal["included_pclass_ids"] if pid in pclass_by_id
            ]

    data = [
        {
            "name": render_template(name_templ, t=t),
            "colour": render_template(colour_templ, t=t, simple_label=simple_label),
            "calibration": render_template(calibration_templ, t=t, included_pclass_names=included_pclass_names),
            "menu": render_template(menu_templ, t=t, url=url, text=text),
        }
        for t in tenants
    ]

    return data
