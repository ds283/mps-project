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


_access = \
"""
{% if asset.in_role_acl(role) %}
    <span class="badge badge-success"><i class="fas fa-check"></i> Role grants access</a>
{% else %}
    <span class="badge badge-danger"><i class="fas fa-times"></i> No access</a>
{% endif %}
"""


_actions = \
"""
<div style="text-align: right;">
    <div class="float-right">
        {% if asset.in_role_acl(role) %}
            <a class="btn btn-sm btn-secondary" href="{{ url_for('documents.remove_role_acl', role_id=role.id, attach_type=type, attach_id=attachment.id) }}">
                <i class="fas fa-times"></i> Remove access
            </a>
        {% else %}
            <a class="btn btn-sm btn-primary" href="{{ url_for('documents.add_role_acl', role_id=role.id, attach_type=type, attach_id=attachment.id) }}">
                <i class="fas fa-times"></i> Grant access
            </a>
        {% endif %}
    </div>
</div>
"""


def acl_role(role_list, asset, attachment, type):
    data = [{'name': r.make_label(),
             'access': render_template_string(_access, asset=asset, role=r),
             'actions': render_template_string(_actions, asset=asset, role=r, attachment=attachment, type=type)}
            for r in role_list]

    return jsonify(data)
