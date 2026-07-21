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
"""

from flask import current_app, render_template, request
from jinja2 import Environment, Template

from ...models import Ticket
from ...tools import ServerSideSQLHandler

# language=jinja2
_ticket = """
<div class="fw-bold"><a class="text-decoration-none" href="{{ url_for('tickets.detail', ticket_id=t.id) }}">{{ t.title }}</a></div>
{% if t.labels.count() > 0 %}
    <div class="d-flex gap-1 flex-wrap mt-1">
        {% for l in t.labels %}<span class="badge rounded-pill" style="{{ l.make_CSS_style() }}">{{ l.name }}</span>{% endfor %}
    </div>
{% endif %}
<div class="small text-muted mt-1">#{{ t.id }} · opened by {{ t.created_by.name if t.created_by else 'someone' }} · <i class="far fa-comment"></i> {{ t.comments.count() }}</div>
"""

# language=jinja2
_status = """
{% set tone = {0: 'primary', 1: 'warning', 2: 'success', 3: 'secondary'}.get(t.status, 'secondary') %}
{% set label = {0: 'Open', 1: 'In progress', 2: 'Resolved', 3: 'Closed'}.get(t.status, 'Unknown') %}
<span class="badge rounded-pill" style="background:var(--bs-{{ tone }}-bg-subtle); color:var(--bs-{{ tone }}-text-emphasis)">{{ label }}</span>
"""

# language=jinja2
_assignee = """
{% if t.assignee %}
    <span class="d-inline-flex align-items-center gap-2">
        <span style="width:26px;height:26px;border-radius:50%;background:var(--bs-primary);color:var(--bs-white);display:inline-flex;align-items:center;justify-content:center;font-size:10px;font-weight:700">{{ t.assignee.initials }}</span>
        <span>{{ t.assignee.name }}</span>
    </span>
{% else %}
    <span class="text-danger fw-semibold">Unassigned</span>
{% endif %}
"""

# language=jinja2
_watchers = """
<span class="text-muted"><i class="fas fa-eye"></i> {{ t.subscriptions.count() }}</span>
"""

# language=jinja2
_scope = """
{% set n = t.scope_classes.count() %}
{% if n == 0 %}<span class="text-muted">General</span>
{% elif n == 1 %}<span class="text-muted">{{ t.scope_classes.first().name }}</span>
{% else %}<span class="text-muted">{{ n }} classes</span>{% endif %}
"""

# language=jinja2
_due = """
{% if t.due_date %}{{ t.due_date.strftime('%d %b %Y') }}{% else %}<span class="text-muted">—</span>{% endif %}
"""


def _build_templ(src: str) -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(src)


def ledger_data(base_query):
    """Render the ledger from a permission-scoped base_query. Returns a DataTables JSON payload."""
    columns = {
        "ticket": {
            "search": Ticket.title,
            "order": Ticket.title,
            "search_collation": "utf8_general_ci",
        },
        "status": {"order": Ticket.status},
        "assignee": {},
        "watchers": {},
        "scope": {},
        "due": {"order": Ticket.due_date},
    }

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        ticket_templ = _build_templ(_ticket)
        status_templ = _build_templ(_status)
        assignee_templ = _build_templ(_assignee)
        watchers_templ = _build_templ(_watchers)
        scope_templ = _build_templ(_scope)
        due_templ = _build_templ(_due)

        def row_formatter(rows):
            return [
                {
                    "ticket": render_template(ticket_templ, t=t),
                    "status": render_template(status_templ, t=t),
                    "assignee": render_template(assignee_templ, t=t),
                    "watchers": render_template(watchers_templ, t=t),
                    "scope": render_template(scope_templ, t=t),
                    "due": render_template(due_templ, t=t),
                }
                for t in rows
            ]

        return handler.build_payload(row_formatter)
