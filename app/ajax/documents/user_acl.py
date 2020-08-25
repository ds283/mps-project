#
# Created by David Seery on 25/05/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_name = \
"""
<a href="mailto:{{ u.email }}">{{ u.name }}</a>
"""


_role = \
"""
{% for role in role_list %}
    {% if u.has_role(role) %}
        {{ role.make_label()|safe }}
    {% endif %}
{% endfor %}
"""


_access = \
"""
{% set in_user_acl = asset.in_user_acl(user) %}
{% set has_role_access = asset.has_role_access(user) %}
{% if in_user_acl %}
    <span class="badge badge-success"><i class="fas fa-check"></i> Has individual access</span>
{% elif has_role_access %}
    {% set eligible_roles = asset.get_eligible_roles(user) %}
    <span class="badge badge-primary"><i class="fas fa-check"></i> Has role-based access</span>
    {% for role in eligible_roles %}
        {{ role.make_label()|safe }}
    {% endfor %}
{% else %}
    <span class="badge badge-danger"><i class="fas fa-times"></i> No access</span>
{% endif %}
"""


_actions = \
"""
{% set in_user_acl = asset.in_user_acl(user) %}
<div style="text-align: right;">
    <div class="float-right">
        {% if in_user_acl %}
            <a class="btn btn-sm btn-secondary" href="{{ url_for('documents.remove_user_acl', user_id=user.id, attach_type=type, attach_id=attachment.id) }}">
                <i class="fas fa-times"></i> Remove access
            </a>
        {% else %}
            <a class="btn btn-sm btn-primary" href="{{ url_for('documents.add_user_acl', user_id=user.id, attach_type=type, attach_id=attachment.id) }}">
                <i class="fas fa-times"></i> Grant access
            </a>
        {% endif %}
    </div>
</div>
"""


def acl_user(user_list, role_list, asset, attachment, type):
    data = [{'name': {'display': render_template_string(_name, u=u),
                      'sortstring': u.last_name + u.first_name},
             'roles': render_template_string(_role, u=u, role_list=role_list),
             'access': render_template_string(_access, user=u, asset=asset),
             'actions': render_template_string(_actions, user=u, asset=asset, attachment=attachment, type=type)}
            for u in user_list]

    return jsonify(data)
