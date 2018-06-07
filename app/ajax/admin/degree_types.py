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


_types_menu = \
"""
<div class="dropdown">
    <button class="btn btn-success btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('admin.edit_degree_type', id=type.id) }}">
                <i class="fa fa-pencil"></i> Edit details
            </a>
        </li>

        {% if type.active %}
            <li><a href="{{ url_for('admin.deactivate_degree_type', id=type.id) }}">
                Make inactive
            </a></li>
        {% else %}
            <li><a href="{{ url_for('admin.activate_degree_type', id=type.id) }}">
                Make active
            </a></li>
        {% endif %}
    </ul>
</div>
"""


def degree_types_data(types):

    data = [{'name': t.name,
             'active': 'Active' if t.active else 'Inactive',
             'menu': render_template_string(_types_menu, type=t)} for t in types]

    return jsonify(data)
