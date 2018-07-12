#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_user_role_template = \
"""
{% if user.has_role('faculty') %}
   <span class="label label-info">faculty</span>
{% elif user.has_role('office') %}
   <span class="label label-info">office</span>
{% elif user.has_role('student') %}
   <span class="label label-info">student</span>
{% endif %}
{% if user.has_role('exec') %}
   <span class="label label-primary">exec</span>
{% endif %}
{% if user.has_role('admin') %}
   <span class="label label-warning">admin</span>
{% endif %}
{% if user.has_role('root') %}
   <span class="label label-danger">sysadmin</span>
{% endif %}
"""

_user_menu_template = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('admin.edit_user', id=user.id) }}">
                <i class="fa fa-pencil"></i> Edit account
            </a>
        </li>
        {% if user.has_role('faculty') %}
            <li>
                <a href="{{ url_for('admin.edit_affiliations', id=user.id) }}">
                    <i class="fa fa-pencil"></i> Edit affiliations
                </a>
            </li>
            <li>
                <a href="{{ url_for('admin.edit_enrollments', id=user.id) }}">
                    <i class="fa fa-pencil"></i> Edit enrollments
                </a>
            </li>
        {% endif %}

        <li {% if user.username == current_user.username or user.has_role('admin') or user.has_role('sysadmin') %}class="disabled"{% endif %}>
            {% if user.is_active %}
                <a {% if user.username != current_user.username or user.has_role('admin') or user.has_role('sysadmin') %}href="{{ url_for('admin.deactivate_user', id=user.id) }}"{% endif %}>
                    Make inactive
                </a>
            {% else %}
                <a href="{{ url_for('admin.activate_user', id=user.id) }}">
                    Make active
                </a>
            {% endif %}
        </li>

        {# current user always has role of at least 'admin', so no need to check here #}
        {% if not user.has_role('student') and not user.has_role('root') %}
            {% if user.has_role('admin') %}
                <li {% if user.username == current_user.username %}class="disabled"{% endif %}>
                    <a {% if user.username != current_user.username %}href="{{ url_for('admin.remove_admin', id=user.id) }}"{% endif %}>Remove admin</a>
                </li>
            {% else %}
                <li {% if not user.is_active %}class="disabled"{% endif %}>
                    <a {% if user.is_active %}href="{{ url_for('admin.make_admin', id=user.id) }}{% endif %}">Make admin</a>
                </li>
            {% endif %}
        {% endif %}

        {% if current_user.has_role('root') and not user.has_role('student') %}
            {% if user.has_role('root') %}
                <li {% if user.username == current_user.username %}class="disabled"{% endif %}>
                    <a {% if user.username != current_user.username %}href="{{ url_for('admin.remove_root', id=user.id) }}"{% endif %}>Remove sysadmin</a>
                </li>
            {% else %}
                <li {% if not user.is_active %}class="disabled"{% endif %}>
                    <a {% if user.is_active %}href="{{ url_for('admin.make_root', id=user.id) }}{% endif %}">Make sysadmin</a>
                </li>
            {% endif %}
        {% endif %}
        
        {# check whether we should offer executive role #}
        {% if not user.has_role('student') %}
            {% if user.has_role('exec') %}
                <li>
                    <a href="{{ url_for('admin.remove_exec', id=user.id) }}">Remove executive</a>
                </li>
            {% else %}
                <li>
                    <a href="{{ url_for('admin.make_exec', id=user.id) }}">Make executive</a>
                </li>
            {% endif %}
        {% endif %}
    </ul>
</div>
"""


def build_data(users):

    data = [{'last': u.last_name,
             'first': u.first_name,
             'user': u.username,
             'email': '<a href="mailto:{m}">{m}</a>'.format(m=u.email),
             'confirm': {
                 'display': u.confirmed_at.strftime("%Y-%m-%d %H:%M:%S"),
                 'timestamp': u.confirmed_at.timestamp()
             } if u.confirmed_at is not None else {
                 'display': '<span class="label label-warning">Not confirmed</span>',
                 'timestamp': None
             },
             'active': '<span class="label label-success">Active</a>' if u.is_active
                 else '<span class="label label-default">Inactive</a>',
             'count': '{c}'.format(c=u.login_count),
             'last_login': {
                 'display': u.last_login_at.strftime("%Y-%m-%d %H:%M:%S"),
                 'timestamp': u.last_login_at.timestamp()
             } if u.last_login_at is not None else {
                 'display': '<span class="label label-default">None</a>',
                 'timestamp': None
             },
             'ip': u.last_login_ip if u.last_login_ip is not None and len(u.last_login_ip) > 0
                 else '<span class="label label-default">None</a>',
             'role': render_template_string(_user_role_template, user=u),
             'menu': render_template_string(_user_menu_template, user=u)} for u in users]

    return jsonify(data)
