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

from ...models import SubmissionPeriodUnit, SubmissionPeriodRecord


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
_dates = """
{% if unit.start_date is not none %}
    <div class="small">{{ unit.start_date.strftime("%a %d %b %Y") }}</div>
{% else %}
    <span class="badge bg-secondary">Not set</span>
{% endif %}
"""


# language=jinja2
_end_date = """
{% if unit.end_date is not none %}
    <div class="small">{{ unit.end_date.strftime("%a %d %b %Y") }}</div>
{% else %}
    <span class="badge bg-secondary">Not set</span>
{% endif %}
"""


# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle table-button" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
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


def _build_dates_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_dates)


def _build_end_date_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_end_date)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def submission_period_units_data(units: List[SubmissionPeriodUnit], period: SubmissionPeriodRecord, url: str = None, text: str = None):
    return_url = url_for("convenor.inspect_period_units", period_id=period.id, url=url, text=text)

    name_templ: Template = _build_name_templ()
    dates_templ: Template = _build_dates_templ()
    end_date_templ: Template = _build_end_date_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "name": render_template(name_templ, unit=u),
            "start_date": {
                "display": render_template(dates_templ, unit=u),
                "sortvalue": u.start_date.isoformat() if u.start_date is not None else "",
            },
            "end_date": {
                "display": render_template(end_date_templ, unit=u),
                "sortvalue": u.end_date.isoformat() if u.end_date is not None else "",
            },
            "menu": render_template(menu_templ, unit=u, return_url=return_url),
        }
        for u in units
    ]

    return data
