#
# Created by David Seery on 25/05/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, get_template_attribute

# language=jinja2
_name = \
"""
<a class="text-decoration-none" href="mailto:{{ u.email }}">{{ u.name }}</a>
"""


# language=jinja2
_role = \
"""
{% for role in role_list %}
    {% if u.has_role(role) %}
        {{ simple_label(role.make_label()) }}
    {% endif %}
{% endfor %}
"""


# language=jinja2
_access = \
"""
{% set in_user_acl = asset.in_user_acl(user) %}
{% set has_role_access = asset.has_role_access(user) %}
{% if in_user_acl %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Has individual access</span>
{% elif has_role_access %}
    {% set eligible_roles = asset.get_eligible_roles(user) %}
    <span class="badge bg-primary"><i class="fas fa-check"></i> Has role-based access</span>
    {% for role in eligible_roles %}
        {{ simple_label(role.make_label()) }}
    {% endfor %}
{% else %}
    <span class="badge bg-danger"><i class="fas fa-times"></i> No access</span>
{% endif %}
"""


# language=jinja2
_actions = \
"""
{% set in_user_acl = asset.in_user_acl(user) %}
<div style="text-align: right;">
    <div class="float-end">
        {% if in_user_acl %}
            <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('documents.remove_user_acl', user_id=user.id, attach_type=type, attach_id=attachment.id) }}">
                <i class="fas fa-trash"></i> Remove access
            </a>
        {% else %}
            <a class="btn btn-sm btn-outline-success" href="{{ url_for('documents.add_user_acl', user_id=user.id, attach_type=type, attach_id=attachment.id) }}">
                <i class="fas fa-check"></i> Grant access
            </a>
        {% endif %}
    </div>
</div>
"""


def acl_user(user_list, role_list, asset, attachment, type):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [{'name': {'display': render_template_string(_name, u=u),
                      'sortstring': u.last_name + u.first_name},
             'roles': render_template_string(_role, u=u, role_list=role_list, simple_label=simple_label),
             'access': render_template_string(_access, user=u, asset=asset),
             'actions': render_template_string(_actions, user=u, asset=asset, attachment=attachment, type=type)}
            for u in user_list]

    return jsonify(data)
