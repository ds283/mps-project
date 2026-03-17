#
# Created by David Seery on 10/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, get_template_attribute, jsonify, render_template, url_for
from jinja2 import Environment, Template

from ...models.emails import EmailTemplate

# language=jinja2
_email_template_type = """
<div class="d-flex flex-column justify-content-start align-items-start gap-2">
    <div class="text-secondary text-uppercase">{{ t.type_name }}</div>
    <div class="d-flex flex-row flex-wrap justify-content-start align-items-center gap-2">
        {% for label in t.labels %}
            {{ simple_label(label.make_label()) }}
        {% endfor %}
    </div>
    <div class="d-flex flex-row flex-wrap justify-content-start align-items-start gap-2">
        {% if t.pclass_id is not none %}
            <div class="small">
                <i class="fas fa-project-diagram fa-fw text-info"></i>
                <strong>Project class:</strong> {{ t.pclass.name }}
            </div>
        {% endif %}
        {% if t.tenant_id is not none %}
            <div class="small">
                <i class="fas fa-building fa-fw text-warning"></i>
                <strong>Tenant:</strong> {{ t.tenant.name }}
            </div>
        {% endif %}
        {% if t.tenant_id is none and t.pclass_id is none %}
            <div class="small text-muted">
                <i class="fas fa-globe fa-fw"></i> Global fallback
            </div>
        {% endif %}
    </div>
</div>
"""

# language=jinja2
_email_template_status = """
<div class="d-flex flex-column justify-content-start align-items-start gap-2">
    <div class="d-flex flex-row flex-wrap justify-content-start align-items-center gap-2">
        {% if t.active %}
            <span class="badge bg-success"><i class="fas fa-check-circle me-1"></i>Active</span>
        {% else %}
            <span class="badge bg-secondary"><i class="fas fa-times-circle me-1"></i>Inactive</span>
        {% endif %}
        {% if t.tenant_id is none and t.pclass_id is none %}
            <span class="badge bg-primary ms-1" data-bs-toggle="tooltip" title="This is the global fallback template for its type">
                <i class="fas fa-globe me-1"></i>Fallback
            </span>
        {% elif t.pclass_id is not none %}
            <span class="badge bg-info ms-1" data-bs-toggle="tooltip" title="Override for project class: {{ t.pclass.name }}">
                <i class="fas fa-project-diagram me-1"></i>PClass override
            </span>
        {% elif t.tenant_id is not none %}
            <span class="badge bg-warning text-dark ms-1" data-bs-toggle="tooltip" title="Override for tenant: {{ t.tenant.name }}">
                <i class="fas fa-building me-1"></i>Tenant override
            </span>
        {% endif %}
    </div>
    <div class="small d-flex flex-column justify-content-start align-items-start gap-1">
        <div class="text-muted">
            Created by
            <a class="text-decoration-none" href="mailto:{{ t.created_by.email }}">{{ t.created_by.name }}</a>
            on
            {% if t.creation_timestamp is not none %}
                {{ t.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
            {% endif %}
        </div>
        {% if t.last_edited_by is not none %}
            <div class="text-muted">
                Last edited by <i class="fas fa-user-circle"></i>
                <a class="text-decoration-none" href="mailto:{{ t.last_edited_by.email }}">{{ t.last_edited_by.name }}</a>
                {% if t.last_edit_timestamp is not none %}
                    {{ t.last_edit_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
                {% endif %}
            </div>
        {% endif %}
        {% if t.last_used is not none %}
            <div class="text-muted">
                Last used on
                {% if t.last_used.timestamp() is not none %}
                    {{ t.last_used.strftime("%a %d %b %Y %H:%M:%S") }}
                {% endif %}
            </div>
        {% endif %}
    </div>
</div>
"""

# language=jinja2
_email_template_subject = """
<div class="text-secondary fw-semibold">{{ t.subject }}</div>
"""

# language=jinja2
_email_template_comment = """
<div class="small text-muted">{{ t.comment }}</div>
"""

# language=jinja2
_email_template_version = """
<span class="badge bg-primary"><i class="fas fa-hashtag"></i> {{ t.version }}</span>
"""

# language=jinja2
_email_template_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_email_template', id=t.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit template&hellip;
        </a>
        {% if t.active %}
            {% if t.tenant_id is none and t.pclass_id is none %}
                <a class="dropdown-item d-flex gap-2 disabled" title="The global fallback template must always be active">
                    <i class="fas fa-times-circle fa-fw"></i> Make inactive
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_email_template', id=t.id) }}">
                    <i class="fas fa-times-circle fa-fw"></i> Make inactive
                </a>
            {% endif %}
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_email_template', id=t.id) }}">
                <i class="fas fa-check-circle fa-fw"></i> Make active
            </a>
        {% endif %}
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.duplicate_email_template', id=t.id) }}">
            <i class="fas fa-copy fa-fw"></i> Duplicate
        </a>
        {% if t.tenant_id is none and t.pclass_id is none %}
            <a class="dropdown-item d-flex gap-2 disabled" title="The global fallback template cannot be deleted">
                <i class="fas fa-trash fa-fw"></i> Delete
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.delete_email_template', id=t.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete
            </a>
        {% endif %}
    </div>
</div>
"""


def _build_type_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_email_template_type)


def _build_status_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_email_template_status)


def _build_subject_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_email_template_subject)


def _build_comment_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_email_template_comment)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_email_template_menu)


def email_templates_data(templates):
    simple_label = get_template_attribute("labels.html", "simple_label")

    # precompile Jinja2 template strings once for the whole batch
    type_templ: Template = _build_type_templ()
    status_templ: Template = _build_status_templ()
    subject_templ: Template = _build_subject_templ()
    comment_templ: Template = _build_comment_templ()
    menu_templ: Template = _build_menu_templ()

    def _process(t: EmailTemplate):
        return {
            "type": render_template(
                type_templ,
                t=t,
                simple_label=simple_label,
            ),
            "subject": render_template(subject_templ, t=t),
            "version": t.version,
            "status": render_template(status_templ, t=t),
            "comment": render_template(comment_templ, t=t),
            "menu": render_template(menu_templ, t=t),
        }

    data = [_process(t) for t in templates]

    return data
