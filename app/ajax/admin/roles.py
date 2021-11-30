#
# Created by David Seery on 16/07/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-o border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('manage_users.edit_role', id=role.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit role
        </a>
    </div>
</div>
"""

def roles_data(roles):

    data = [{'name': r.name,
             'description': r.description,
             'color': r.make_label(r.colour),
             'menu': render_template_string(_menu, role=r)} for r in roles]

    return jsonify(data)
