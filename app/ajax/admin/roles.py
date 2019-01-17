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


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('admin.edit_role', id=role.id) }}">
                <i class="fa fa-pencil"></i> Edit role
            </a>
        </li>
    </ul>
</div>
"""

def roles_data(roles):

    data = [{'name': r.name,
             'description': r.description,
             'color': r.make_label(r.colour),
             'menu': render_template_string(_menu, role=r)} for r in roles]

    return jsonify(data)
