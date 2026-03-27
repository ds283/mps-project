#
# Created by David Seery on 27/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import List

from flask import current_app, render_template
from flask_security import current_user
from jinja2 import Template, Environment

from ...models import StudentData, StudentJournalEntry

# language=jinja2
_timestamp = """
<span class="small">{{ entry.created_timestamp.strftime("%a %d %b %Y %H:%M") }}</span>
"""

# language=jinja2
_year = """
{% if entry.main_config is not none %}
    <span class="small">{{ entry.main_config.year }}/{{ (entry.main_config.year + 1) | string | truncate(2, True, '') }}</span>
{% else %}
    <span class="text-secondary small"><i class="fas fa-times-circle"></i> Unknown</span>
{% endif %}
"""

# language=jinja2
_classes = """
{% set configs = entry.project_classes.all() %}
{% if configs | length > 0 %}
    {% for config in configs %}
        <span class="badge bg-secondary me-1">{{ config.project_class.abbreviation }}</span>
    {% endfor %}
{% else %}
    <span class="text-secondary small"><i class="fas fa-minus-circle"></i> None</span>
{% endif %}
"""

# language=jinja2
_entry_preview = """
{% if entry.entry %}
    <span class="small text-muted">{{ entry.entry | striptags | truncate(120) }}</span>
{% else %}
    <span class="text-secondary small"><em>Empty</em></span>
{% endif %}
"""

# language=jinja2
_owner = """
{% if entry.owner is not none %}
    <span class="small">{{ entry.owner.name }}</span>
{% else %}
    <span class="badge bg-info text-dark">Auto</span>
{% endif %}
"""

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% if entry.owner is not none and entry.owner_id == current_user.id %}
            <a class="dropdown-item d-flex gap-2"
               href="{{ url_for('convenor.edit_journal_entry', entry_id=entry.id, url=url_for('convenor.student_journal_inspector', student_id=student.id)) }}">
                <i class="fas fa-pencil-alt fa-fw"></i> Edit...
            </a>
            <a class="dropdown-item d-flex gap-2"
               href="{{ url_for('convenor.delete_journal_entry', entry_id=entry.id, url=url_for('convenor.student_journal_inspector', student_id=student.id)) }}">
                <i class="fas fa-trash fa-fw"></i> Delete
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled">
                <i class="fas fa-pencil-alt fa-fw"></i> Edit (not owner)
            </a>
        {% endif %}
    </div>
</div>
"""


def _build_templ(template_str: str) -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(template_str)


def journal_data(entries: List[StudentJournalEntry], student: StudentData):
    timestamp_templ: Template = _build_templ(_timestamp)
    year_templ: Template = _build_templ(_year)
    classes_templ: Template = _build_templ(_classes)
    entry_preview_templ: Template = _build_templ(_entry_preview)
    owner_templ: Template = _build_templ(_owner)
    menu_templ: Template = _build_templ(_menu)

    def _process(e: StudentJournalEntry):
        return {
            "timestamp": {
                "display": render_template(timestamp_templ, entry=e),
                "value": e.created_timestamp.timestamp() if e.created_timestamp else 0,
            },
            "year": render_template(year_templ, entry=e),
            "classes": render_template(classes_templ, entry=e),
            "entry": render_template(entry_preview_templ, entry=e),
            "owner": render_template(owner_templ, entry=e),
            "actions": render_template(menu_templ, entry=e, student=student, current_user=current_user),
        }

    return [_process(e) for e in entries]
