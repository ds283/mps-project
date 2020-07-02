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


_supervisors_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('admin.edit_supervisor', id=role.id) }}">
                <i class="fa fa-pencil"></i> Edit details...
            </a>
        </li>

        <li>
            {% if role.active %}
                <a href="{{ url_for('admin.deactivate_supervisor', id=role.id) }}">
                    <i class="fa fa-wrench"></i> Make inactive
                </a>
            {% else %}
                <a href="{{ url_for('admin.activate_supervisor', id=role.id) }}">
                    <i class="fa fa-wrench"></i> Make active
                </a>
            {% endif %}
        </li>
    </ul>
</div>
"""


_active = \
"""
{% if r.active %}
    <span class="badge badge-success"><i class="fa fa-check"></i> Active</span>
{% else %}
    <span class="badge badge-warning"><i class="fa fa-times"></i> Inactive</span>
{% endif %}
"""


_colour = \
"""
{{ r.make_label(r.colour)|safe }}
"""


_name = \
"""
{{ r.name }} {{ r.make_label()|safe }}
"""


def supervisors_data(roles):

    data = [{'role': render_template_string(_name, r=r),
             'colour': render_template_string(_colour, r=r),
             'active': render_template_string(_active, r=r),
             'menu': render_template_string(_supervisors_menu, role=r)} for r in roles]

    return jsonify(data)
