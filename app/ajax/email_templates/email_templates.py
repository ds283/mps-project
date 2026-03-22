#
# Created by David Seery on 22/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List

from flask import current_app, get_template_attribute, render_template, url_for
from jinja2 import Environment, Template

from ...models.emails import _TYPE_NAMES, EmailTemplate

# language=jinja2
_email_template_type = """
<div class="d-flex flex-column justify-content-start align-items-start gap-2">
    <div class="text-secondary text-uppercase">{{ type_name }}</div>
    {% if template is not none %}
        <div class="d-flex flex-row flex-wrap justify-content-start align-items-center gap-2">
            {% for label in template.labels %}
                {{ simple_label(label.make_label()) }}
            {% endfor %}
        </div>
    {% endif %}
</div>
"""

# language=jinja2
_email_template_status = """
{% if template is not none %}
    <div class="d-flex flex-column justify-content-start align-items-start gap-2">
        <div class="d-flex flex-row flex-wrap justify-content-start align-items-center gap-2">
            {% if template.active %}
                <span class="badge bg-success"><i class="fas fa-check-circle me-1"></i>Active</span>
            {% else %}
                <span class="badge bg-secondary"><i class="fas fa-times-circle me-1"></i>Inactive</span>
            {% endif %}
            <span class="badge bg-info ms-1" data-bs-toggle="tooltip" title="Override for project class: {{ pclass.name }}">
                <i class="fas fa-project-diagram me-1"></i>Project class override
            </span>
        </div>
        <div class="small d-flex flex-column justify-content-start align-items-start gap-1">
            <div class="text-muted">
                Created by
                <a class="text-decoration-none" href="mailto:{{ template.created_by.email }}">{{ template.created_by.name }}</a>
                on
                {% if template.creation_timestamp is not none %}
                    {{ template.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
                {% endif %}
            </div>
            {% if template.last_edited_by is not none %}
                <div class="text-muted">
                    Last edited by <i class="fas fa-user-circle"></i>
                    <a class="text-decoration-none" href="mailto:{{ template.last_edited_by.email }}">{{ template.last_edited_by.name }}</a>
                    {% if template.last_edit_timestamp is not none %}
                        {{ template.last_edit_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
                    {% endif %}
                </div>
            {% endif %}
            {% if template.last_used is not none %}
                <div class="text-muted">
                    Last used on
                    {% if template.last_used.timestamp() is not none %}
                        {{ template.last_used.strftime("%a %d %b %Y %H:%M:%S") }}
                    {% endif %}
                </div>
            {% endif %}
        </div>
    </div>
{% else %}
    <div class="d-flex flex-row justify-content-start align-items-center gap-1 text-info">
        <i class="fas fa-info-circle"></i>
        <span class="fst-italic">Using a default template</span>
    </div>
{% endif %}
"""

# language=jinja2
_email_template_subject = """
{% if template is not none %}
    <div class="text-secondary fw-semibold">{{ template.subject }}</div>
{% else %}
    <div class="d-flex flex-row justify-content-start align-items-center gap-1 text-info">
        <i class="fas fa-info-circle"></i>
        <span class="fst-italic">Using a default template</span>
    </div>
{% endif %}
"""

# language=jinja2
_email_template_comment = """
{% if template is not none %}
    <div class="small text-muted">{{ template.comment }}</div>
{% endif %}
"""

# language=jinja2
_email_template_version = """
{% if template is not none %}
    <span class="badge bg-primary"><i class="fas fa-hashtag"></i> {{ template.version }}</span>
{% else %}
    <span class="text-muted">—</span>
{% endif %}
"""

# language=jinja2
_email_template_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% if template is not none %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.edit_email_template', pclass_id=pclass.id, template_id=template.id) }}">
                <i class="fas fa-pencil-alt fa-fw"></i> Edit template&hellip;
            </a>
            {% if template.active %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.deactivate_email_template', pclass_id=pclass.id, template_id=template.id) }}">
                    <i class="fas fa-times-circle fa-fw"></i> Make inactive
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.activate_email_template', pclass_id=pclass.id, template_id=template.id) }}">
                    <i class="fas fa-check-circle fa-fw"></i> Make active
                </a>
            {% endif %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.duplicate_email_template', pclass_id=pclass.id, template_id=template.id) }}">
                <i class="fas fa-copy fa-fw"></i> Duplicate
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.delete_email_template', pclass_id=pclass.id, template_id=template.id) }}">
                <i class="fas fa-trash fa-fw"></i> Delete
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.view_default_template', pclass_id=pclass.id, template_type=template_type) }}">
                <i class="fas fa-envelope fa-fw"></i> View default&hellip;
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.create_email_template', pclass_id=pclass.id, template_type=template_type) }}">
                <i class="fas fa-plus fa-fw"></i> Create override
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


def _build_version_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_email_template_version)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_email_template_menu)


def template_data(pclass, template_list: List):
    """
    Generate DataTables data for email templates.

    :param pclass: ProjectClass instance
    :param template_list: List of tuples (template_type, template_or_none)
    :return: List of dictionaries for DataTables
    """
    simple_label = get_template_attribute("labels.html", "simple_label")

    # precompile Jinja2 template strings once for the whole batch
    type_templ: Template = _build_type_templ()
    status_templ: Template = _build_status_templ()
    subject_templ: Template = _build_subject_templ()
    comment_templ: Template = _build_comment_templ()
    version_templ: Template = _build_version_templ()
    menu_templ: Template = _build_menu_templ()

    def _process(template_type: int, template):
        type_name = _TYPE_NAMES.get(
            template_type, f"Unknown email template type ({template_type})"
        )

        return {
            "type": render_template(
                type_templ,
                type_name=type_name,
                template=template,
                simple_label=simple_label,
            ),
            "subject": render_template(subject_templ, template=template),
            "version": render_template(version_templ, template=template),
            "status": render_template(status_templ, template=template, pclass=pclass),
            "comment": render_template(comment_templ, template=template),
            "menu": render_template(
                menu_templ,
                template=template,
                pclass=pclass,
                template_type=template_type,
            ),
        }

    data = [
        _process(template_type, template) for template_type, template in template_list
    ]

    return data
