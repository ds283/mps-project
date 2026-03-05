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

from ...models import SupervisionEventTemplate, SubmissionPeriodUnit


# language=jinja2
_name = """
<div class="fw-semibold">{{ event.name }}</div>
<div class="small text-muted">
    {{ event_label }}
</div>
"""


# language=jinja2
_target_role = """
<span class="badge bg-secondary">{{ role_label }}</span>
"""


# language=jinja2
_monitor = """
{% if event.monitor_attendance %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Yes</span>
{% else %}
    <span class="badge bg-secondary">No</span>
{% endif %}
"""


# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle table-button" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_unit_event_template', template_id=event.id, url=return_url) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.delete_unit_event_template', template_id=event.id) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    </div>
</div>
"""


def _build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def _build_target_role_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_target_role)


def _build_monitor_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_monitor)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def supervision_event_templates_data(templates: List[SupervisionEventTemplate], unit: SubmissionPeriodUnit, url: str = None, text: str = None):
    return_url = url_for("convenor.inspect_unit_event_templates", unit_id=unit.id, url=url, text=text)

    name_templ: Template = _build_name_templ()
    target_role_templ: Template = _build_target_role_templ()
    monitor_templ: Template = _build_monitor_templ()
    menu_templ: Template = _build_menu_templ()

    data = [
        {
            "name": render_template(
                name_templ,
                event=t,
                event_label=t._event_labels.get(t.type, "Unknown"),
            ),
            "target_role": render_template(
                target_role_templ,
                event=t,
                role_label=t._role_labels.get(t.target_role, "Unknown"),
            ),
            "monitor": render_template(monitor_templ, event=t),
            "menu": render_template(menu_templ, event=t, return_url=return_url),
        }
        for t in templates
    ]

    return data
