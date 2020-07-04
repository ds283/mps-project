#
# Created by David Seery on 29/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


name = \
"""
<a href="mailto:{{ u.email }}">{{ u.name }}</a>
<div>
    {{ 'REPACTIVE'|safe }}
    {% if u.student_data and u.student_data is not none %}
        {% if u.student_data.intermitting %}
            <span class="badge badge-warning">INTERMITTING</span>
        {% endif %}
        {% set state = u.student_data.workflow_state %}
        {% if state == u.student_data.WORKFLOW_APPROVAL_QUEUED %}
            <span class="badge badge-warning">Approval: Queued</span>
        {% elif state == u.student_data.WORKFLOW_APPROVAL_REJECTED %}
            <span class="badge badge-danger">Approval: Rejected</span>
        {% elif state == u.student_data.WORKFLOW_APPROVAL_VALIDATED %}
            <span class="badge badge-success"><i class="fa fa-check"></i> Approved</span>
        {% else %}
            <span class="badge badge-danger">Unknown validation</span>
        {% endif %}
    {% endif %}
    {% if f %}
        <div>
            {% if f.is_convenor %}
                {% for item in f.convenor_list %}
                    {{ item.make_label('Convenor ' + item.abbreviation)|safe }}
                {% endfor %}
            {% endif %}
        </div>
    {% endif %}
    {% set theme = u.ui_theme if u.ui_theme is defined else 'default' %}
    {% if theme == 'default' %}
        <span class="badge badge-primary">Default</span>
    {% elif theme == 'flat' %}
        <span class="badge badge-primary">Flat</span>
    {% elif theme == 'dark' %}
        <span class="badge badge-primary">Dark</span>
    {% else %}
        <span class="badge badge-danger">Unknown theme</span>
    {% endif %}
    {% if u.last_email %}
        <span class="badge badge-info">Last notify {{ u.last_email.strftime("%a %d %b %Y %H:%M:%S") }}</span>
    {% endif %}
</div>
"""


menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <div class="dropdown-header">Edit</div>
        <a class="dropdown-item" href="{{ url_for('manage_users.edit_user', id=user.id, pane=pane) }}">
            <i class="fa fa-cogs"></i> Account settings...
        </a>
        {% if user.has_role('faculty') %}
            <a class="dropdown-item" href="{{ url_for('manage_users.edit_affiliations', id=user.id, pane=pane) }}">
                <i class="fa fa-cogs"></i> Affiliations...
            </a>
            <a class="dropdown-item" href="{{ url_for('manage_users.edit_enrollments', id=user.id, pane=pane) }}">
                <i class="fa fa-cogs"></i> Enrollments...
            </a>
        {% endif %}

        <div role="separator" class="dropdown-divider"></div>
        <div class="dropdown-header">Operations</div>

        {% set disabled = (user.username == cuser.username or user.has_role('admin') or user.has_role('sysadmin')) %}
        {% if user.is_active %}
            <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if user.username != cuser.username or user.has_role('admin') or user.has_role('sysadmin') %}href="{{ url_for('manage_users.deactivate_user', id=user.id) }}"{% endif %}>
                <i class="fa fa-wrench"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item {% if disabled %}disabled{% endif %}" href="{{ url_for('manage_users.activate_user', id=user.id) }}">
                <i class="fa fa-wrench"></i> Make active
            </a>
        {% endif %}

        {# current user always has role of at least 'admin', so no need to check here #}
        {% if not user.has_role('student') and not user.has_role('root') %}
            {% if user.has_role('admin') %}
                {% set disabled = (user.username == cuser.username) %}
                <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if user.username != cuser.username %}href="{{ url_for('manage_users.remove_admin', id=user.id) }}"{% endif %}>
                    <i class="fa fa-wrench"></i> Remove admin
                </a>
            {% else %}
                {% set disabled = (not user.is_active) %} 
                <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if user.is_active %}href="{{ url_for('manage_users.make_admin', id=user.id) }}{% endif %}">
                    <i class="fa fa-wrench"></i> Promote to admin
                </a>
            {% endif %}
        {% endif %}

        {% if cuser.has_role('root') and not user.has_role('student') %}
            {% if user.has_role('root') %}
                {% set disabled = (user.username == cuser.username) %}
                <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if user.username != cuser.username %}href="{{ url_for('manage_users.remove_root', id=user.id) }}"{% endif %}>
                    <i class="fa fa-wrench"></i> Remove sysadmin
                </a>
            {% else %}
                {% set disabled = (not user.is_active) %}
                <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if user.is_active %}href="{{ url_for('manage_users.make_root', id=user.id) }}{% endif %}">
                    <i class="fa fa-wrench"></i> Promote to sysadmin
                </a>
            {% endif %}
        {% endif %}

        {# check whether we should offer role editor in the menu #}
        {% if cuser.has_role('root') and not user.has_role('student') %}
            <a class="dropdown-item" href="{{ url_for('manage_users.assign_roles', id=user.id, pane=pane) }}">
                <i class="fa fa-wrench"></i> Assign roles...
            </a>
        {% endif %}
        
        {% if cuser.has_role('root') and not cuser.has_role('student') %}
            <div role="separator" class="dropdown-divider"></div>
            <div class="dropdown-header">Superuser functions</div>
            <a class="dropdown-item" href="{{ url_for('admin.login_as', id=user.id) }}">
                <i class="fa fa-user"></i> Login as user
            </a>
        {% endif %}
    </div>
</div>
"""
