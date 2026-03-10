#
# Created by David Seery on 10/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, get_template_attribute, current_app, url_for, render_template

from jinja2 import Template, Environment

from ...models.emails import EmailTemplate


# Human-readable names for each template type
_TYPE_NAMES = {
    EmailTemplate.BACKUP_REPORT_THINNING: "Backup: Report thinning",
    EmailTemplate.CLOSE_SELECTION_CONVENOR: "Close selection: Convenor",
    EmailTemplate.GO_LIVE_CONVENOR: "Go live: Convenor",
    EmailTemplate.GO_LIVE_FACULTY: "Go live: Faculty",
    EmailTemplate.GO_LIVE_SELECTOR: "Go live: Selector",
    EmailTemplate.MAINTENANCE_LOST_ASSETS: "Maintenance: Lost assets",
    EmailTemplate.MAINTENANCE_UNATTACHED_ASSETS: "Maintenance: Unattached assets",
    EmailTemplate.MARKING_MARKER: "Marking: Marker",
    EmailTemplate.MARKING_SUPERVISOR: "Marking: Supervisor",
    EmailTemplate.MATCHING_DRAFT_NOTIFY_FACULTY: "Matching: Draft notify faculty",
    EmailTemplate.MATCHING_DRAFT_NOTIFY_STUDENTS: "Matching: Draft notify students",
    EmailTemplate.MATCHING_DRAFT_UNNEEDED_FACULTY: "Matching: Draft unneeded faculty",
    EmailTemplate.MATCHING_FINAL_NOTIFY_FACULTY: "Matching: Final notify faculty",
    EmailTemplate.MATCHING_FINAL_NOTIFY_STUDENTS: "Matching: Final notify students",
    EmailTemplate.MATCHING_FINAL_UNNEEDED_FACULTY: "Matching: Final unneeded faculty",
    EmailTemplate.MATCHING_GENERATED: "Matching: Generated",
    EmailTemplate.MATCHING_NOTIFY_EXCEL_REPORT: "Matching: Notify Excel report",
    EmailTemplate.NOTIFICATIONS_REQUEST_MEETING: "Notifications: Request meeting",
    EmailTemplate.NOTIFICATIONS_FACULTY_ROLLUP: "Notifications: Faculty rollup",
    EmailTemplate.NOTIFICATIONS_FACULTY_SINGLE: "Notifications: Faculty single",
    EmailTemplate.NOTIFICATIONS_STUDENT_ROLLUP: "Notifications: Student rollup",
    EmailTemplate.NOTIFICATIONS_STUDENT_SINGLE: "Notifications: Student single",
    EmailTemplate.PROJECT_CONFIRMATION_REMINDER: "Project confirmation: Reminder",
    EmailTemplate.PROJECT_CONFIRMATION_REQUESTED: "Project confirmation: Requested",
    EmailTemplate.PROJECT_CONFIRMATION_NEW_COMMENT: "Project confirmation: New comment",
    EmailTemplate.PROJECT_CONFIRMATION_REVISE_REQUEST: "Project confirmation: Revise request",
    EmailTemplate.PUSH_FEEDBACK_PUSH_TO_MARKER: "Push feedback: To marker",
    EmailTemplate.PUSH_FEEDBACK_PUSH_TO_STUDENT: "Push feedback: To student",
    EmailTemplate.PUSH_FEEDBACK_PUSH_TO_SUPERVISOR: "Push feedback: To supervisor",
    EmailTemplate.SCHEDULING_AVAILABILITY_REMINDER: "Scheduling: Availability reminder",
    EmailTemplate.SCHEDULING_AVAILABILITY_REQUEST: "Scheduling: Availability request",
    EmailTemplate.SCHEDULING_DRAFT_NOTIFY_FACULTY: "Scheduling: Draft notify faculty",
    EmailTemplate.SCHEDULING_DRAFT_NOTIFY_STUDENTS: "Scheduling: Draft notify students",
    EmailTemplate.SCHEDULING_DRAFT_UNNEEDED_FACULTY: "Scheduling: Draft unneeded faculty",
    EmailTemplate.SCHEDULING_FINAL_NOTIFY_FACULTY: "Scheduling: Final notify faculty",
    EmailTemplate.SCHEDULING_FINAL_NOTIFY_STUDENTS: "Scheduling: Final notify students",
    EmailTemplate.SCHEDULING_FINAL_UNNEEDED_FACULTY: "Scheduling: Final unneeded faculty",
    EmailTemplate.SCHEDULING_GENERATED: "Scheduling: Generated",
    EmailTemplate.SERVICES_CC_EMAIL: "Services: CC email",
    EmailTemplate.SERVICES_SEND_EMAIL: "Services: Send email",
    EmailTemplate.STUDENT_NOTIFICATIONS_CHOICES_RECEIVED: "Student notifications: Choices received",
    EmailTemplate.STUDENT_NOTIFICATIONS_CHOICES_RECEIVED_PROXY: "Student notifications: Choices received (proxy)",
    EmailTemplate.SYSTEM_GARBAGE_COLLECTION: "System: Garbage collection",
}


def get_type_name(type_id):
    return _TYPE_NAMES.get(type_id, f"Unknown type ({type_id})")


# language=jinja2
_email_template_type = """
<div>{{ type_name }}</div>
{% for label in t.labels %}
    {{ simple_label(label.make_label()) }}
{% endfor %}
"""

# language=jinja2
_email_template_status = """
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
"""

# language=jinja2
_email_template_scope = """
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
                    <i class="fas fa-times-circle fa-fw"></i> Deactivate
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_email_template', id=t.id) }}">
                    <i class="fas fa-times-circle fa-fw"></i> Deactivate
                </a>
            {% endif %}
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_email_template', id=t.id) }}">
                <i class="fas fa-check-circle fa-fw"></i> Activate
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


def _build_scope_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_email_template_scope)


def _build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_email_template_menu)


def email_templates_data(templates):
    simple_label = get_template_attribute("labels.html", "simple_label")

    # precompile Jinja2 template strings once for the whole batch
    type_templ: Template = _build_type_templ()
    status_templ: Template = _build_status_templ()
    scope_templ: Template = _build_scope_templ()
    menu_templ: Template = _build_menu_templ()

    def _process(t: EmailTemplate):
        return {
            "type": render_template(type_templ, t=t, type_name=get_type_name(t.type), simple_label=simple_label),
            "subject": t.subject,
            "version": t.version,
            "scope": render_template(scope_templ, t=t),
            "status": render_template(status_templ, t=t),
            "menu": render_template(menu_templ, t=t),
        }

    data = [_process(t) for t in templates]

    return data
