#
# Created by David Seery on 29/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

menu = \
    """
    <div class="dropdown">
        <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
            Actions
            <span class="caret"></span>
        </button>
        <ul class="dropdown-menu dropdown-menu-right">
            <li class="dropdown-header">Edit</li>
            <li>
                <a href="{{ url_for('admin.edit_user', id=user.id, pane=pane) }}">
                    <i class="fa fa-pencil"></i> Account settings
                </a>
            </li>
            {% if user.has_role('faculty') %}
                <li>
                    <a href="{{ url_for('admin.edit_affiliations', id=user.id, pane=pane) }}">
                        <i class="fa fa-pencil"></i> Affiliations
                    </a>
                </li>
                <li>
                    <a href="{{ url_for('admin.edit_enrollments', id=user.id, pane=pane) }}">
                        <i class="fa fa-pencil"></i> Enrollments
                    </a>
                </li>
            {% endif %}
    
            <li role="separator" class="divider"></li>
            <li class="dropdown-header">Operations</li>
    
            <li {% if user.username == current_user.username or user.has_role('admin') or user.has_role('sysadmin') %}class="disabled"{% endif %}>
                {% if user.is_active %}
                    <a {% if user.username != current_user.username or user.has_role('admin') or user.has_role('sysadmin') %}href="{{ url_for('admin.deactivate_user', id=user.id) }}"{% endif %}>
                        <i class="fa fa-wrench"></i> Make inactive
                    </a>
                {% else %}
                    <a href="{{ url_for('admin.activate_user', id=user.id) }}">
                        <i class="fa fa-wrench"></i> Make active
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
            
            {% if current_user.has_role('root') and not current_user.has_role('student') %}
                <li role="separator" class="divider"></li>
                <li class="dropdown-header">Superuser functions</li>
                <li>
                    <a href="{{ url_for('admin.login_as', id=user.id) }}">Login as user</a>
                </li>
            {% endif %}
        </ul>
    </div>
    """
