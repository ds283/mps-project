#
# Created by David Seery on 29/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app
from jinja2 import Environment, Template

# language=jinja2
_name = """
<a class="text-decoration-none" href="mailto:{{ u.email }}">{{ u.name }}</a>
<div>
    {% if u.currently_active %}<span class="badge bg-success">ACTIVE</span>{% endif %}
    {% set sd = u.student_data %}
    {% if sd is defined and sd is not none %}
        {% set programme = sd.programme %}
        {% set type = programme.degree_type %}
        <div class="mt-1 small d-flex flex-row flex-wrap justify-content-start align-items-start gap-2">
            <span class="{% if type.level >= type.LEVEL_UG and type.level <= type.LEVEL_PGR %}text-secondary{% else %}text-danger{% endif %}">{{ type._level_text(type.level) }}</div>
            {% set state = sd.workflow_state %}
            {% if state == sd.WORKFLOW_APPROVAL_QUEUED %}
                <span class="badge bg-warning text-dark">Approval: Queued</span>
            {% elif state == sd.WORKFLOW_APPROVAL_REJECTED %}
                <span class="badge bg-danger">Approval: In progress</span>
            {% elif state == sd.WORKFLOW_APPROVAL_VALIDATED %}
                <span class="badge bg-success"><i class="fas fa-check"></i> Approved</span>
            {% else %}
                <span class="badge bg-danger">Approval: Unknown state</span>
            {% endif %}
        </div>
        <div class="mt-1 small d-flex flex-row flex-wrap justify-content-start align-items-start gap-2">
            {% if sd.ATAS_restricted %}
                <span class="badge bg-danger">ATAS restricted</span>
            {% endif %}
            {% if sd.intermitting %}
                <span class="badge bg-warning text-dark">TWD</span>
            {% endif %}
            {% if sd.dyspraxia_sticker %}
                <span class="badge bg-primary">Support</span>
            {% endif %}
            {% if sd.dyslexia_sticker %}
                <span class="badge bg-primary">SpLD</span>
            {% endif %}
        </div>
    {% endif %}
    {% if f is defined and f is not none %}
        {% if f.office is not none and f.office|length > 0 %}
            <div class="mt-1 small text-primary fw-semibold">{{ f.office }}</div>
        {% endif %}
        <div class="mt-1 small d-flex flex-row flex-wrap justify-content-start align-items-start gap-2">
            {% if f.is_convenor %}
                {% for item in f.convenor_list %}
                    {{ simple_label(item.make_label(item.abbreviation), prefix='Convenor') }}
                {% endfor %}
            {% endif %}
        </div>
    {% endif %}
    {% if u.confirmed_at %}
        <div class="mt-1 small text-muted"><i class="fas fa-calendar"></i> Confirmed at {{ u.confirmed_at.strftime("%Y-%m-%d %H:%M:%S") }}</div>
    {% else %}
        <div class="mt-1 small text-danger"><i class="fas fa-exclamation-circle"></i> Not confirmed</div>
    {% endif %}
    {% if u.last_email %}
        <div class="mt-1 small text-muted"><i class="fas fa-envelope"></i> Last notify {{ u.last_email.strftime("%d/%m/%y") }}</div>
    {% endif %}
    <div class="mt-1 small d-flex flex-row flex-wrap justify-content-start align-items-start gap-2">
        {% for tenant in u.tenants %}
            {{ simple_label(tenant.make_label(tenant.name)) }}
        {% endfor %}
    </div>
</div>
"""


# language=jinja2
_menu = """
{% set user_is_student  = user.has_role('student') %}
{% set user_is_faculty  = user.has_role('faculty') %}
{% set user_is_admin    = user.has_role('admin') %}
{% set user_is_root     = user.has_role('root') %}
{% set cuser_is_admin   = cuser.has_role('admin') %}
{% set cuser_is_root    = cuser.has_role('root') %}
{% set cuser_is_student = cuser.has_role('student') %}
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <div class="dropdown-header">Edit</div>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.edit_user', id=user.id, pane=pane) }}">
            <i class="fas fa-sliders-h fa-fw"></i> Account settings...
        </a>
        {% if user_is_faculty %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.edit_affiliations', id=user.id, pane=pane) }}">
                <i class="fas fa-cogs fa-fw"></i> Affiliations...
            </a>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.edit_enrollments', id=user.id, pane=pane) }}">
                <i class="fas fa-cogs fa-fw"></i> Enrolments...
            </a>
        {% elif user_is_student %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('student.timeline', student_id=user.id, url=url_for('manage_users.edit_users_students'), text='student accounts') }}">
                <i class="fas fa-history fa-fw"></i> Show history...
            </a>
            {% if user.student_data is not none %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('convenor.student_journal_inspector', student_id=user.student_data.id, url=url_for('manage_users.edit_users_students'), text='student accounts') }}">
                    <i class="fas fa-book fa-fw"></i> View journal...
                </a>
            {% endif %}
        {% endif %}

        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Operations</div>

        {% set disabled = (user.username == cuser.username or user_is_admin or user_is_root) %}
        {% if user.is_active %}
            <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if user.username != cuser.username or user.has_role('admin') or user.has_role('sysadmin') %}href="{{ url_for('manage_users.deactivate_user', id=user.id) }}"{% endif %}>
                <i class="fas fa-times-circle fa-fw"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" href="{{ url_for('manage_users.activate_user', id=user.id) }}">
                <i class="fas fa-check-circle fa-fw"></i> Make active
            </a>
        {% endif %}

        {# current user always has role of at least 'admin', so no need to check here #}
        {% if not user_is_student and not user_is_root %}
            {% if user_is_admin %}
                {% set disabled = (user.username == cuser.username) %}
                <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if user.username != cuser.username %}href="{{ url_for('manage_users.remove_admin', id=user.id) }}"{% endif %}>
                    <i class="fas fa-wrench fa-fw"></i> Remove admin
                </a>
            {% else %}
                {% set disabled = (not user.is_active) %} 
                <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if user.is_active %}href="{{ url_for('manage_users.make_admin', id=user.id) }}{% endif %}">
                    <i class="fas fa-wrench fa-fw"></i> Promote to admin
                </a>
            {% endif %}
        {% endif %}

        {% if cuser_is_root and not user_is_student %}
            {% if user_is_root %}
                {% set disabled = (user.username == cuser.username) %}
                <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if user.username != cuser.username %}href="{{ url_for('manage_users.remove_root', id=user.id) }}"{% endif %}>
                    <i class="fas fa-wrench fa-fw"></i> Remove sysadmin
                </a>
            {% else %}
                {% set disabled = (not user.is_active) %}
                <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if user.is_active %}href="{{ url_for('manage_users.make_root', id=user.id) }}{% endif %}">
                    <i class="fas fa-wrench fa-fw"></i> Promote to sysadmin
                </a>
            {% endif %}
        {% endif %}

        {# check whether we should offer role editor in the menu #}
        {% if cuser_is_root and not user_is_student %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.assign_roles', id=user.id, pane=pane) }}">
                <i class="fas fa-wrench fa-fw"></i> Assign roles...
            </a>
        {% endif %}
        
        {% if cuser_is_root and not cuser_is_student %}
            <div role="separator" class="dropdown-divider"></div>
            <div class="dropdown-header">Superuser functions</div>
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.login_as', id=user.id) }}">
                <i class="fas fa-user-circle fa-fw"></i> Login as user
            </a>
        {% endif %}
    </div>
</div>
"""

# language=jinja2
_active = """
{% if u.active %}
    <div class="d-flex flex-row justify-content-start align-items-center gap-1 text-success"><i class="fas fa-check-circle"></i> Active</span>
{% else %}
    <div class="d-flex flex-row justify-content-start align-items-center gap-1 text-secondary"><i class="fas fa-times-circle"></i> Inactive</span>
{% endif %}
"""

# language=jinja2
_cohort = """
{{ simple_label(s.cohort_label) }}
"""

# language=jinja2
_programme = """
{{ simple_label(s.programme.label) }}
"""

# language=jinja2
_academic_year = """
{{ simple_label(s.academic_year_label(show_details=True)) }}
"""


def build_name_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_name)


def build_menu_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_menu)


def build_active_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_active)


def build_programme_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_programme)


def build_cohort_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_cohort)


def build_academic_year_templ() -> Template:
    env: Environment = current_app.jinja_env
    return env.from_string(_academic_year)
