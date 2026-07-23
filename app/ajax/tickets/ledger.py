#
# Created by David Seery on 22/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Server-side DataTables endpoint for the ticket ledger (design screen 1a), reused by the convenor
dashboard (3a) and the faculty/office inbox (2c). The caller passes a fully permission-scoped
base_query; this module only adds sorting/searching/pagination and row rendering.

Uses ServerSideInMemoryHandler rather than ServerSideSQLHandler: Ticket.title/description are
EncryptedType (AesEngine, fixed IV — deterministic but not LIKE-searchable at the SQL level), so a
free-text search has to run against the decrypted value in Python. This mirrors the existing
project pattern for searching encrypted/computed fields — see
app/convenor/marking_feedback.py:_faculty_workload's "search"/"order" callables. Ticket volumes
(low hundreds/thousands) make this a non-issue performance-wise.
"""

from datetime import datetime

from flask import current_app, render_template, request
from jinja2 import Environment, Template

from ...models import Ticket
from ...tools import ServerSideInMemoryHandler

# language=jinja2
_select = """
<input type="checkbox" class="form-check-input tk-row-check" value="{{ t.id }}" aria-label="Select ticket">
"""

# language=jinja2
_ticket = """
{% set tone = {0: 'success', 1: 'warning', 2: 'primary', 3: 'secondary'}.get(t.status, 'secondary') %}
{% set status_label = {0: 'Open', 1: 'In progress', 2: 'Resolved', 3: 'Closed'}.get(t.status, 'Unknown') %}
<div class="d-flex align-items-center gap-2 flex-wrap">
    <a class="fw-semibold text-decoration-none" href="{{ url_for('tickets.detail', ticket_id=t.id, url=return_url, origin=origin, pclass=pclass_id) }}">{{ t.title }}</a>
    <span class="tk-pill" style="background:var(--bs-{{ tone }}-bg-subtle); color:var(--bs-{{ tone }}-text-emphasis); padding:2px 9px; font-size:11px">
        <span class="tk-dot" style="background:var(--bs-{{ tone }}-text-emphasis)"></span>{{ status_label }}
    </span>
</div>
{% if t.labels.count() > 0 %}
    <div class="d-flex gap-1 flex-wrap mt-1">
        {% for l in t.labels %}<span class="tk-label" style="{{ l.make_CSS_style() }}">{{ l.name }}</span>{% endfor %}
    </div>
{% endif %}
<div class="small text-muted mt-1">#{{ t.id }} · opened by {{ t.created_by.name if t.created_by else 'someone' }} · <i class="far fa-comment"></i> {{ t.comments.count() }}</div>
{% if watchers %}
    <div class="d-flex align-items-center mt-1" style="margin-left:-4px">
        {% for user in watchers %}
            <span class="tk-av" style="width:26px;height:26px;font-size:11px;margin-left:4px;border:2px solid var(--bs-body-bg);background:{{ user.avatar_colour }}" title="{{ user.name }}">{{ user.initials }}</span>
        {% endfor %}
        {% if watchers_extra %}<span class="small text-muted ms-1">+{{ watchers_extra }}</span>{% endif %}
    </div>
{% endif %}
"""

# language=jinja2
_assignee = """
{% if t.assignee %}
    <span class="d-inline-flex align-items-center gap-2">
        <span class="tk-av" style="width:32px;height:32px;font-size:12px;background:{{ t.assignee.avatar_colour }}">{{ t.assignee.initials }}</span>
        <span>{{ t.assignee.name }}</span>
    </span>
{% else %}
    <span class="text-danger fw-semibold">Unassigned</span>
{% endif %}
"""

# language=jinja2
_scope = """
{% set subjects = t.subjects.all() %}
{% if subjects | length == 0 %}
    <span class="text-muted">General</span>
{% elif subjects | length == 1 %}
    {% set s = subjects[0] %}
    {% if s.is_tombstoned %}
        <div class="text-muted fst-italic" title="This student record has been deleted">{{ s.deleted_snapshot_label }}</div>
        <span class="tk-label" style="background:{{ kind_colours.get(s.kind, '#6c757d') }};color:#fff">{{ 'Submitter' if s.kind == 0 else 'Selector' }} (deleted)</span>
    {% elif s.kind == 0 and s.submitting_student %}
        <div class="text-muted">{{ s.submitting_student.student.user.name if s.submitting_student.student and s.submitting_student.student.user else 'Student' }}</div>
        <span class="tk-label" style="background:{{ kind_colours[0] }};color:#fff">Submitter</span>
    {% elif s.kind == 1 and s.selecting_student %}
        <div class="text-muted">{{ s.selecting_student.student.user.name if s.selecting_student.student and s.selecting_student.student.user else 'Student' }}</div>
        <span class="tk-label" style="background:{{ kind_colours[1] }};color:#fff">Selector</span>
    {% elif s.kind == 2 and s.project_class %}<span class="text-muted">{{ s.project_class.name }}</span>
    {% else %}<span class="text-muted">General</span>
    {% endif %}
{% else %}
    {% set n = t.scope_classes.count() %}
    {% if n <= 1 %}<span class="text-muted">{{ subjects | length }} subjects</span>
    {% else %}<span class="text-muted">{{ n }} classes</span>{% endif %}
{% endif %}
"""

# language=jinja2
_due = """
{% if t.due_date %}
    {% set overdue = t.due_date < now and t.status in open_states %}
    {% if overdue %}
        <div class="text-danger">Overdue</div>
        <div class="text-danger">{{ t.due_date.strftime('%d %b %Y') }}</div>
    {% else %}
        <span>{{ t.due_date.strftime('%d %b %Y') }}</span>
    {% endif %}
{% else %}<span class="text-muted">—</span>{% endif %}
"""


def _build_templ(src: str) -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(src)


_WATCHERS_SHOWN = 3

# subject-kind chip colours for the Scope cell (0 = submitter, 1 = selector), reusing hues from the
# ticket-label palette (app/tickets/labels.py:LABEL_PALETTE) rather than the workflow-status tones,
# so "what kind of subject" reads as visually distinct from "what state is it in".
_KIND_COLOURS = {0: "#087990", 1: "#59359a"}


def _watchers_for(t):
    """Watchers to show in the Ticket cell's avatar stack, excluding the assignee — they're
    already shown in their own column, so repeating them here (which happens whenever the sole
    watcher is the auto-subscribed assignee) added a redundant, near-empty row."""
    users = [sub.user for sub in t.subscriptions if sub.user is not None and sub.user_id != t.assignee_id]
    return users[:_WATCHERS_SHOWN], max(0, len(users) - _WATCHERS_SHOWN)


def ledger_data(base_query, return_url=None, origin=None, pclass_id=None):
    """Render the ledger from a permission-scoped base_query. Returns a DataTables JSON payload.

    `return_url` is the originating page's URL (inbox or convenor ledger); it is threaded onto each
    row's ticket-detail link as the canonical `url` return param (see
    `.claude/rules/return-link-url-text.md`) so the detail-view breadcrumb returns the user to the
    surface they came from.

    `origin` ("convenor"/"faculty") and `pclass_id` identify which surface the row was opened from,
    so the detail view can render the matching dashboard chrome (see app/tickets/detail.py)."""
    columns = {
        "ticket": {"search": lambda t: t.title},
        "assignee": {"order": lambda t: t.assignee.name if t.assignee else None},
        "scope": {},
        "due": {"order": lambda t: t.due_date},
    }

    with ServerSideInMemoryHandler(request, base_query, columns) as handler:
        select_templ = _build_templ(_select)
        ticket_templ = _build_templ(_ticket)
        assignee_templ = _build_templ(_assignee)
        scope_templ = _build_templ(_scope)
        due_templ = _build_templ(_due)

        now = datetime.now()
        open_states = Ticket.OPEN_STATES

        def row_formatter(rows):
            rendered = []
            for t in rows:
                watchers, watchers_extra = _watchers_for(t)
                rendered.append(
                    {
                        "select": render_template(select_templ, t=t),
                        "ticket": render_template(
                            ticket_templ,
                            t=t,
                            watchers=watchers,
                            watchers_extra=watchers_extra,
                            return_url=return_url,
                            origin=origin,
                            pclass_id=pclass_id,
                        ),
                        "assignee": render_template(assignee_templ, t=t),
                        "scope": render_template(scope_templ, t=t, kind_colours=_KIND_COLOURS),
                        "due": render_template(due_templ, t=t, now=now, open_states=open_states),
                    }
                )
            return rendered

        return handler.build_payload(row_formatter)
