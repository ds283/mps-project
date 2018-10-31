#
# Created by David Seery on 2018-10-02.
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
            <a href="{{ url_for('admin.edit_building', id=b.id) }}">
                <i class="fa fa-pencil"></i> Edit details...
            </a>
        </li>

        {% if b.active %}
            <li><a href="{{ url_for('admin.deactivate_building', id=b.id) }}">
                <i class="fa fa-wrench"></i> Make inactive
            </a></li>
        {% else %}
            <li><a href="{{ url_for('admin.activate_building', id=b.id) }}">
                <i class="fa fa-wrench"></i> Make active
            </a></li>
        {% endif %}
    </ul>
</div>
"""


_active = \
"""
{% if b.active %}
    <span class="label label-success"><i class="fa fa-check"></i> Active</span>
{% else %}
    <span class="label label-warning"><i class="fa fa-times"></i> Inactive</span>
{% endif %}
"""


def buildings_data(buildings):

    data = [{'name': b.name,
             'colour': b.make_label(b.colour),
             'active': render_template_string(_active, b=b),
             'menu': render_template_string(_menu, b=b)} for b in buildings]

    return jsonify(data)
