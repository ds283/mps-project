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
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
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

_active = \
"""
{% if t.active %}
    <span class="label label-success"><i class="fa fa-check"></i> Active</span>
{% else %}
    <span class="label label-warning"><i class="fa fa-times"></i> Inactive</span>
{% endif %}
"""


def degree_types_data(types):

    data = [{'name': t.name,
             'active': render_template_string(_active, t=t),
             'menu': render_template_string(_types_menu, type=t)} for t in types]

    return jsonify(data)
