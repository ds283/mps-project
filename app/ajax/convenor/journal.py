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
from jinja2 import Environment, Template

from ...models import StudentJournalEntry

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
_type = """
<span class="badge d-inline-flex align-items-center gap-1"
      style="color: {{ entry.type_colour }}; background-color: {{ entry.type_background }};">
    <i class="fas {{ entry.type_icon }}"></i> {{ entry.type_label }}
</span>
"""

# language=jinja2
_title = """
<div class="d-flex align-items-center gap-2">
    {% if unread %}<span class="udot"></span>{% endif %}
    <a class="text-decoration-none"
       href="{{ url_for('convenor.view_journal_entry', entry_id=entry.id, url=return_url, text=return_text) }}">
        {% if entry.title %}
            <span class="fw-semibold">{{ entry.title }}</span>
        {% else %}
            <span class="text-secondary fst-italic">Untitled</span>
        {% endif %}
    </a>
</div>
{% if entry.entry %}
    <div class="small text-muted mt-1">{{ entry.entry | striptags | truncate(100) }}</div>
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
               href="{{ url_for('convenor.edit_journal_entry', entry_id=entry.id, url=return_url, text=return_text) }}">
                <i class="fas fa-pencil-alt fa-fw"></i> Edit...
            </a>
            <a class="dropdown-item d-flex gap-2"
               href="{{ url_for('convenor.delete_journal_entry', entry_id=entry.id, url=return_url) }}">
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


# language=jinja2
_tab_entry = """
<div class="d-flex align-items-center gap-2">
    {% if unread %}<span class="udot"></span>{% endif %}
    <a class="text-decoration-none fw-semibold" href="#"
       data-bs-toggle="offcanvas" data-bs-target="#journalDrawer"
       data-student-id="{{ entry.student_id }}"
       data-student-name="{{ entry.student.user.name if entry.student and entry.student.user else '' }}">
        {% if entry.title %}{{ entry.title }}{% else %}<span class="fst-italic">Untitled</span>{% endif %}
    </a>
    {% if unread %}<span class="recent-tag">new</span>{% endif %}
</div>
{% if entry.entry %}
    <div class="small text-muted mt-1">{{ entry.entry | striptags | truncate(100) }}</div>
{% endif %}
"""

# language=jinja2
_tab_student = """
{% if entry.student and entry.student.user %}
    <a class="text-decoration-none" href="{{ url_for('convenor.student_journal_inspector', student_id=entry.student_id) }}">
        {{ entry.student.user.name }}
    </a>
{% else %}
    <span class="text-secondary small">Unknown student</span>
{% endif %}
{% if pclass %}<span class="badge bg-secondary ms-1">{{ pclass.abbreviation }}</span>{% endif %}
"""

# language=jinja2
_tab_owner = """
{% if entry.owner is not none %}
    <span class="small">{{ entry.owner.name }}</span>
{% else %}
    <span class="badge bg-secondary">Auto</span>
{% endif %}
"""

# language=jinja2
_tab_review = """
<button type="button" class="btn btn-sm btn-outline-primary"
        data-bs-toggle="offcanvas" data-bs-target="#journalDrawer"
        data-student-id="{{ entry.student_id }}"
        data-student-name="{{ entry.student.user.name if entry.student and entry.student.user else '' }}">
    Open
</button>
"""


def _build_templ(template_str: str) -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(template_str)


def journal_tab_data(entries: List[StudentJournalEntry], pclass=None) -> list:
    """
    Row formatter for the aggregate per-project-class Journal tab (all entries visible to
    the convenor, across selectors and submitters). Unlike journal_data() (single-student
    inspector), each row also identifies the student and is flagged unread via DT_RowClass
    so the client-side table can highlight it, matching the drawer/overview conventions.
    """
    entry_templ: Template = _build_templ(_tab_entry)
    student_templ: Template = _build_templ(_tab_student)
    type_templ: Template = _build_templ(_type)
    owner_templ: Template = _build_templ(_tab_owner)
    timestamp_templ: Template = _build_templ(_timestamp)
    review_templ: Template = _build_templ(_tab_review)

    def _process(e: StudentJournalEntry):
        unread = not e.is_read_by(current_user)
        return {
            "entry": render_template(entry_templ, entry=e, unread=unread),
            "student": render_template(student_templ, entry=e, pclass=pclass),
            "type": render_template(type_templ, entry=e),
            "owner": render_template(owner_templ, entry=e),
            "timestamp": render_template(timestamp_templ, entry=e),
            "review": render_template(review_templ, entry=e, unread=unread),
            "DT_RowClass": "unread-row" if unread else "",
        }

    return [_process(e) for e in entries]


def journal_data(entries: List[StudentJournalEntry], return_url: str = None, return_text: str = "Back to journal") -> list:
    timestamp_templ: Template = _build_templ(_timestamp)
    year_templ: Template = _build_templ(_year)
    classes_templ: Template = _build_templ(_classes)
    type_templ: Template = _build_templ(_type)
    title_templ: Template = _build_templ(_title)
    owner_templ: Template = _build_templ(_owner)
    menu_templ: Template = _build_templ(_menu)

    def _process(e: StudentJournalEntry):
        unread = not e.is_read_by(current_user)
        return {
            "timestamp": render_template(timestamp_templ, entry=e),
            "year": render_template(year_templ, entry=e),
            "classes": render_template(classes_templ, entry=e),
            "type": render_template(type_templ, entry=e),
            "title": render_template(title_templ, entry=e, return_url=return_url, return_text=return_text, unread=unread),
            "owner": render_template(owner_templ, entry=e),
            "actions": render_template(menu_templ, entry=e, current_user=current_user, return_url=return_url, return_text=return_text),
            "DT_RowClass": "unread-row" if unread else "",
        }

    return [_process(e) for e in entries]
