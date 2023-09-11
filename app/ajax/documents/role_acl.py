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
_access = \
"""
{% if asset.in_role_acl(role) %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Role grants access</a>
{% else %}
    <span class="badge bg-danger"><i class="fas fa-times"></i> No access</a>
{% endif %}
"""


# language=jinja2
_actions = \
"""
<div style="text-align: right;">
    <div class="float-end">
        {% if asset.in_role_acl(role) %}
            <a class="btn btn-sm btn-outline-secondary" href="{{ url_for('documents.remove_role_acl', role_id=role.id, attach_type=type, attach_id=attachment.id) }}">
                <i class="fas fa-trash"></i> Remove access
            </a>
        {% else %}
            <a class="btn btn-sm btn-outline-success" href="{{ url_for('documents.add_role_acl', role_id=role.id, attach_type=type, attach_id=attachment.id) }}">
                <i class="fas fa-check"></i> Grant access
            </a>
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_name = \
"""
{{ simple_label(r.make_label()) }}
"""


def acl_role(role_list, asset, attachment, type):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [{'name': render_template_string(_name, r=r, simple_label=simple_label),
             'access': render_template_string(_access, asset=asset, role=r),
             'actions': render_template_string(_actions, asset=asset, role=r, attachment=attachment, type=type)}
            for r in role_list]

    return jsonify(data)
