#
# Created by David Seery on 05/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List

from flask import current_app, render_template, url_for
from jinja2 import Template, Environment

from ...models import SubmissionPeriodUnit, SubmissionPeriodRecord, SupervisionEventTemplate


# language=jinja2
_name = """
<div class="fw-semibold">{{ unit.name }}</div>
{% if unit.start_date is not none or unit.end_date is not none %}
    <div class="small text-muted">
        {% if unit.start_date is not none %}
            <span>{{ unit.start_date.strftime("%a %d %b %Y") }}</span>
        {% endif %}
        {% if unit.start_date is not none and unit.end_date is not none %}
            &ndash;
        {% endif %}
        {% if unit.end_date is not none %}
            <span>{{ unit.end_date.strftime("%a %d %b %Y") }}</span>
        {% endif %}
    </div>
{% endif %}
"""


# language=jinja2
_start_date = """
{% if unit.start_date is not none %}
    <div><i class="fas fa-calendar"></i> {{ unit.start_date.strftime("%a %d %b %Y") }}</div>
{% else %}
    <span class="badge bg-secondary">Not set</span>
{% endif %}
"""


# language=jinja2
_end_date = """
{% if unit.end_date is not none %}
    <div><i class="fas fa-calendar"></i> {{ unit.end_date.strftime("%a %d %b %Y") }}</div>
{% else %}
    <span class="badge bg-secondary">Not set</span>
{% endif %}
"""


# language=jinja2
_event_templates = """
{% set templates = unit.event_templates.all() %}
{% if templates %}
    <div class="d-flex flex-column justify-content-start align-items-start gap-1">
        {% for t in templates %}
            <div class="d-flex flex-row flex-wrap justify-content-start align-items-center gap-2 small">
                <a class="link-primary text-decoration-none" href="{{ url_for('convenor.edit_unit_event_template', template_id=t.id, url=return_url) }}">{{ t.name }}</a>                
                <span class="badge bg-secondary">{{ t._role_labels.get(t.target_role, "?") }}</span>
                <span class="text-muted">({{ t._event_labels.get(t.type, "?") }})</span>
            </div>
        {% endfor %}
        <a class="btn btn-xs btn-outline-secondary small mt-2" href="{{ url_for('convenor.inspect_unit_event_templates', unit_id=unit.id, url=return_url, text="submission period units inspector") }}">Inspect events&hellip;</a>
    </div>
{% else %}
    <span class="text-muted small">None</span>
{% endif %}
"""


# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle table-button" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.inspect_unit_event_templates', unit_id=unit.id, url=return_url, text='submission period units inspector') }}">
            <i class="fas fa-calendar-alt fa-fw"></i> Event templates...
        </a>
        <div role="separator" class="dropdown-divider"></div>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_period_unit', unit_id=unit.id, url=return_url) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.delete_period_unit', unit_id=unit.id, url=return_url) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    </div>
</div>
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_start_date_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_start_date)


def _build_end_date_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_end_date)


def _build_event_templates_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_event_templates)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def submission_period_units_data(units: List[SubmissionPeriodUnit], period: SubmissionPeriodRecord, url: str = None, text: str = None):
    return_url = url_for("convenor.inspect_period_units", period_id=period.id, url=url, text=text)

    name_templ: Template = _build_name_templ()
    start_date_templ: Template = _build_start_date_templ()
    end_date_templ: Template = _build_end_date_templ()
    event_templates_templ: Template = _build_event_templates_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "name": render_template(name_templ, unit=u),
            "start_date": {
                "display": render_template(start_date_templ, unit=u),
                "sortvalue": u.start_date.isoformat() if u.start_date is not None else "",
            },
            "end_date": {
                "display": render_template(end_date_templ, unit=u),
                "sortvalue": u.end_date.isoformat() if u.end_date is not None else "",
            },
            "event_templates": render_template(event_templates_templ, unit=u, return_url=return_url),
            "menu": render_template(menu_templ, unit=u, return_url=return_url),
        }
        for u in units
    ]

    return data
