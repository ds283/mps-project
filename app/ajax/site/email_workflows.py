#
# Created by David Seery on 24/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import humanize
from flask import render_template_string, url_for
from sqlalchemy import func

from ...database import db
from ...models import EmailWorkflow, EmailWorkflowItem

# ---------------------------------------------------------------------------
# Jinja2 template fragments – workflow list
# ---------------------------------------------------------------------------

# language=jinja2
_workflow_name_col = """
<div class="text-primary">{{ w.name }}</div>
{% if pclasses %}
    <div class="mt-1">
        {% for pc in pclasses %}
            <span class="badge bg-secondary me-1">{{ pc.abbreviation }}</span>
        {% endfor %}
    </div>
{% else %}
    <div class="text-muted small mt-1"><em>No project classes</em></div>
{% endif %}
"""

# language=jinja2
_workflow_status_col = """
<div class="d-flex flex-row flex-wrap gap-2">
    {% if w.completed %}
        <span class="badge bg-success"><i class="fas fa-check-circle fa-fw"></i> Completed</span>
        {% if w.completed_timestamp %}
            <span class="text-muted small">{{ w.completed_timestamp.strftime("%a %d %b %Y %H:%M") }}</span>
        {% endif %}
    {% else %}
        <span class="badge bg-primary"><i class="fas fa-clock fa-fw"></i> In progress</span>
    {% endif %}
    {% if w.paused %}
        <span class="badge bg-warning text-dark"><i class="fas fa-pause-circle fa-fw"></i> Paused</span>
    {% endif %}
</div>
"""

# language=jinja2
_workflow_template_col = """
<div class="small">
    <div><span class="text-muted">Type:</span> {{ w.template.type_name }}</div>
    <div><span class="text-muted">Max attachment:</span> {{ max_attach }}</div>
</div>
"""

# language=jinja2
_workflow_send_time_col = """
<div>{{ w.send_time.strftime("%a %d %b %Y") }}</div>
<div class="text-muted small">{{ w.send_time.strftime("%H:%M") }}</div>
"""

# language=jinja2
_workflow_items_col = """
<div class="small">
    <div>
        <span class="badge bg-secondary">{{ total }}</span>
        total
    </div>
    {% if total > 0 %}
        <div class="mt-1">
            <span class="badge bg-success">{{ sent }}</span> sent &nbsp;
            <span class="badge bg-primary">{{ pending }}</span> pending
        </div>
        {% if errors > 0 %}
            <div class="mt-1">
                <span class="badge bg-danger"><i class="fas fa-exclamation-triangle fa-fw"></i> {{ errors }}</span>
                error{{ 's' if errors != 1 else '' }}
            </div>
        {% endif %}
        {% if item_paused > 0 %}
            <div class="mt-1">
                <span class="badge bg-warning text-dark"><i class="fas fa-pause fa-fw"></i> {{ item_paused }}</span>
                item{{ 's' if item_paused != 1 else '' }} paused
            </div>
        {% endif %}
    {% endif %}
</div>
"""

# language=jinja2
_workflow_details_col = """
<div class="small text-muted">
    {% if w.created_by %}
        <div><i class="fas fa-user fa-fw"></i> Created by
            <strong>{{ w.created_by.name }}</strong>
        </div>
    {% endif %}
    {% if w.creation_timestamp %}
        <div><i class="fas fa-calendar-plus fa-fw"></i>
            {{ w.creation_timestamp.strftime("%a %d %b %Y %H:%M") }}
        </div>
    {% endif %}
    {% if w.last_edit_id %}
        <div class="mt-1"><i class="fas fa-edit fa-fw"></i> Edited by
            <strong>{{ w.last_edited_by.name if w.last_edited_by else '#' ~ w.last_edit_id }}</strong>
        </div>
        {% if w.last_edit_timestamp %}
            <div><i class="fas fa-calendar-check fa-fw"></i>
                {{ w.last_edit_timestamp.strftime("%a %d %b %Y %H:%M") }}
            </div>
        {% endif %}
    {% endif %}
</div>
"""

# language=jinja2
_workflow_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2"
           href="{{ url_for('emailworkflow.workflow_items', id=w.id, url=url_for('emailworkflow.email_workflows'), text='Email workflows') }}">
            <i class="fas fa-search fa-fw"></i> Inspect&hellip;
        </a>
        {% if not w.completed %}
            <div class="dropdown-divider"></div>
            {% if w.paused %}
                <a class="dropdown-item d-flex gap-2"
                   href="{{ url_for('emailworkflow.unpause_workflow', id=w.id) }}">
                    <i class="fas fa-play fa-fw"></i> Unpause
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2"
                   href="{{ url_for('emailworkflow.pause_workflow', id=w.id) }}">
                    <i class="fas fa-pause fa-fw"></i> Pause
                </a>
            {% endif %}
            <a class="dropdown-item d-flex gap-2"
               href="{{ url_for('emailworkflow.confirm_delete_workflow', id=w.id) }}">
                <i class="fas fa-trash fa-fw text-danger"></i> Delete&hellip;
            </a>
            <div class="dropdown-divider"></div>
            <a class="dropdown-item d-flex gap-2"
               href="{{ url_for('emailworkflow.edit_workflow', id=w.id) }}">
                <i class="fas fa-pen fa-fw"></i> Edit&hellip;
            </a>
        {% endif %}
    </div>
</div>
"""


def email_workflow_data(workflows):
    data = []
    for w in workflows:
        pclasses = list(w.pclasses.all())
        max_attach = (
            humanize.naturalsize(w.max_attachment_size)
            if w.max_attachment_size
            else "None"
        )

        # Item counts via sub-queries for efficiency
        total = (
            db.session.query(func.count(EmailWorkflowItem.id))
            .filter(EmailWorkflowItem.workflow_id == w.id)
            .scalar()
            or 0
        )
        sent = (
            db.session.query(func.count(EmailWorkflowItem.id))
            .filter(
                EmailWorkflowItem.workflow_id == w.id,
                EmailWorkflowItem.sent_timestamp.isnot(None),
            )
            .scalar()
            or 0
        )
        pending = (
            db.session.query(func.count(EmailWorkflowItem.id))
            .filter(
                EmailWorkflowItem.workflow_id == w.id,
                EmailWorkflowItem.sent_timestamp.is_(None),
            )
            .scalar()
            or 0
        )
        errors = (
            db.session.query(func.count(EmailWorkflowItem.id))
            .filter(
                EmailWorkflowItem.workflow_id == w.id,
                EmailWorkflowItem.error_condition.is_(True),
            )
            .scalar()
            or 0
        )
        item_paused = (
            db.session.query(func.count(EmailWorkflowItem.id))
            .filter(
                EmailWorkflowItem.workflow_id == w.id,
                EmailWorkflowItem.paused.is_(True),
            )
            .scalar()
            or 0
        )

        data.append(
            {
                "name": render_template_string(
                    _workflow_name_col, w=w, pclasses=pclasses
                ),
                "status": render_template_string(_workflow_status_col, w=w),
                "template": render_template_string(
                    _workflow_template_col, w=w, max_attach=max_attach
                ),
                "send_time": render_template_string(_workflow_send_time_col, w=w),
                "items": render_template_string(
                    _workflow_items_col,
                    w=w,
                    total=total,
                    sent=sent,
                    pending=pending,
                    errors=errors,
                    item_paused=item_paused,
                ),
                "details": render_template_string(_workflow_details_col, w=w),
                "menu": render_template_string(_workflow_menu, w=w),
            }
        )
    return data


# ---------------------------------------------------------------------------
# Jinja2 template fragments – workflow item list
# ---------------------------------------------------------------------------

# language=jinja2
_item_name_col = """
<div>
    {% set recipients = item.recipient_addresses %}
    {% if recipients %}
        {% for addr in recipients %}
            <div class="small"><a class="text-decoration-none" href="mailto:{{ addr }}">{{ addr }}</a></div>
        {% endfor %}
    {% else %}
        <span class="badge bg-warning text-dark">No recipients</span>
    {% endif %}
</div>
{% if item.subject_override or item.body_override or item.callbacks_list %}
    <div class="mt-1 small">
        {% if item.subject_override %}
            <span class="badge bg-info text-dark me-1"
                  data-bs-toggle="tooltip"
                  title="Subject override is set">Subject&nbsp;override</span>
        {% endif %}
        {% if item.body_override %}
            <span class="badge bg-info text-dark me-1"
                  data-bs-toggle="tooltip"
                  title="Body override is set">Body&nbsp;override</span>
        {% endif %}
        {% if item.callbacks_list %}
            <span class="badge bg-secondary me-1"
                  data-bs-toggle="tooltip"
                  title="Callbacks configured">Callbacks</span>
        {% endif %}
    </div>
{% endif %}
"""

# language=jinja2
_item_status_col = """
<div class="d-flex flex-row flex-wrap gap-2">
    {% if item.sent_timestamp %}
        <span class="badge bg-success"><i class="fas fa-check fa-fw"></i> Sent</span>
        <span class="text-muted small">{{ item.sent_timestamp.strftime("%a %d %b %Y %H:%M") }}</span>
    {% else %}
        <span class="badge bg-primary"><i class="fas fa-clock fa-fw"></i> Pending</span>
    {% endif %}
    {% if item.paused %}
        <span class="badge bg-warning text-dark"><i class="fas fa-pause fa-fw"></i> Paused</span>
    {% endif %}
</div>
"""

# language=jinja2
_item_error_col = """
<div class="small">
    <div>
        <span class="text-muted">Attempts:</span>
        <span class="badge {% if item.send_attempts > 0 %}bg-secondary{% else %}bg-light text-dark border{% endif %}">
            {{ item.send_attempts }}
        </span>
    </div>
    {% if item.error_condition %}
        <div class="mt-1">
            <span class="badge bg-danger"><i class="fas fa-exclamation-triangle fa-fw"></i> Error</span>
        </div>
        {% if item.error_message %}
            <div class="mt-1 text-danger small" style="max-width: 280px; word-wrap: break-word;">
                {{ item.error_message|truncate(120) }}
            </div>
        {% endif %}
    {% endif %}
</div>
"""

# language=jinja2
_item_task_col = """
<div class="small">
    {% if item.send_in_progress_timestamp %}
        <div>
            <span class="text-muted">In progress:</span>
            {{ item.send_in_progress_timestamp.strftime("%a %d %b %Y %H:%M") }}
        </div>
    {% endif %}
    {% if item.celery_send_in_progress_task_id %}
        <div class="mt-1">
            <span class="text-muted">Task ID:</span>
            <code class="small">{{ item.celery_send_in_progress_task_id|truncate(30) }}</code>
        </div>
    {% endif %}
    {% if item.email_log_id %}
        <div class="mt-1">
            <a class="text-decoration-none small"
               href="{{ url_for('admin.display_email', id=item.email_log_id, url=return_url, text=return_text) }}">
                <i class="fas fa-envelope fa-fw"></i> View in email log
            </a>
        </div>
    {% endif %}
</div>
"""

# language=jinja2
_item_details_col = """
<div class="small text-muted">
    {% if item.created_by %}
        <div><i class="fas fa-user fa-fw"></i> Created by
            <strong>{{ item.created_by.name }}</strong>
        </div>
    {% endif %}
    {% if item.creation_timestamp %}
        <div><i class="fas fa-calendar-plus fa-fw"></i>
            {{ item.creation_timestamp.strftime("%a %d %b %Y %H:%M") }}
        </div>
    {% endif %}
    {% if item.last_edit_id %}
        <div class="mt-1"><i class="fas fa-edit fa-fw"></i> Edited by
            <strong>{{ item.last_edited_by.name if item.last_edited_by else '#' ~ item.last_edit_id }}</strong>
        </div>
        {% if item.last_edit_timestamp %}
            <div><i class="fas fa-calendar-check fa-fw"></i>
                {{ item.last_edit_timestamp.strftime("%a %d %b %Y %H:%M") }}
            </div>
        {% endif %}
    {% endif %}
</div>
"""

# language=jinja2
_item_attachments_col = """
{% set attach_list = item.attachments.all() %}
{% if attach_list %}
    <div class="small">
        {% set generated = attach_list | selectattr("generated_asset_id") | list %}
        {% set submitted = attach_list | selectattr("submitted_asset_id") | list %}
        {% set temporary = attach_list | selectattr("temporary_asset_id") | list %}

        {% if generated %}
            <div class="fw-semibold text-muted">Generated ({{ generated|length }})</div>
            {% for att in generated %}
                <div class="ms-2">
                    <i class="fas fa-file fa-fw"></i>
                    {{ att.name or att.generated_asset.target_name or att.generated_asset.unique_name or '—' }}
                </div>
            {% endfor %}
        {% endif %}
        {% if submitted %}
            <div class="fw-semibold text-muted {% if generated %}mt-1{% endif %}">Submitted ({{ submitted|length }})</div>
            {% for att in submitted %}
                <div class="ms-2">
                    <i class="fas fa-file-upload fa-fw"></i>
                    {{ att.name or att.submitted_asset.target_name or att.submitted_asset.unique_name or '—' }}
                </div>
            {% endfor %}
        {% endif %}
        {% if temporary %}
            <div class="fw-semibold text-muted {% if generated or submitted %}mt-1{% endif %}">Temporary ({{ temporary|length }})</div>
            {% for att in temporary %}
                <div class="ms-2">
                    <i class="fas fa-file-alt fa-fw"></i>
                    {{ att.name or att.temporary_asset.unique_name or '—' }}
                </div>
            {% endfor %}
        {% endif %}
    </div>
{% else %}
    <span class="text-muted small"><em>None</em></span>
{% endif %}
"""

# language=jinja2
_item_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2"
           href="{{ url_for('emailworkflow.preview_item', id=item.id, url=return_url, text=return_text) }}">
            <i class="fas fa-eye fa-fw"></i> Preview...
        </a>
        <div class="dropdown-divider"></div>
        {% if not item.sent_timestamp %}
            {% if item.paused %}
                <a class="dropdown-item d-flex gap-2"
                   href="{{ url_for('emailworkflow.unpause_item', id=item.id, url=return_url) }}">
                    <i class="fas fa-play fa-fw"></i> Unpause
                </a>
            {% else  %}
                <a class="dropdown-item d-flex gap-2"
                   href="{{ url_for('emailworkflow.pause_item', id=item.id, url=return_url) }}">
                    <i class="fas fa-pause fa-fw"></i> Pause
                </a>
            {% endif %}
            <a class="dropdown-item d-flex gap-2"
               href="{{ url_for('emailworkflow.confirm_delete_item', id=item.id, url=return_url, text=return_text) }}">
                <i class="fas fa-trash fa-fw text-danger"></i> Delete...
            </a>
            <div class="dropdown-divider"></div>
        {% endif %}
        <div class="dropdown-header">Show content</div>
        <a class="dropdown-item d-flex gap-2"
           href="{{ url_for('emailworkflow.item_payloads', id=item.id, url=return_url, text=return_text) }}">
            <i class="fas fa-code fa-fw"></i> Payloads&hellip;
        </a>
        {% if item.subject_override or item.body_override %}
            <a class="dropdown-item d-flex gap-2"
               href="{{ url_for('emailworkflow.item_overrides', id=item.id, url=return_url, text=return_text) }}">
                <i class="fas fa-pen fa-fw"></i> Overrides...
            </a>
        {% endif %}
    </div>
</div>
"""


def email_workflow_item_data(items, return_url, return_text):
    data = []
    for item in items:
        data.append(
            {
                "name": render_template_string(_item_name_col, item=item),
                "status": render_template_string(_item_status_col, item=item),
                "error": render_template_string(_item_error_col, item=item),
                "task": render_template_string(
                    _item_task_col,
                    item=item,
                    return_url=return_url,
                    return_text=return_text,
                ),
                "details": render_template_string(_item_details_col, item=item),
                "attachments": render_template_string(_item_attachments_col, item=item),
                "menu": render_template_string(
                    _item_menu,
                    item=item,
                    return_url=return_url,
                    return_text=return_text,
                ),
            }
        )
    return data
