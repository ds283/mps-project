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


_programmes_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('admin.edit_degree_programme', id=programme.id) }}">
                <i class="fa fa-pencil"></i> Edit details
            </a>
        </li>

        {% if programme.active %}
            <li><a href="{{ url_for('admin.deactivate_degree_programme', id=programme.id) }}">
                Make inactive
            </a></li>
        {% else %}
            {% if programme.available() %}
                <li><a href="{{ url_for('admin.activate_degree_programme', id=programme.id) }}">
                    Make active
                </a></li>
            {% else %}
                <li class="disabled"><a>
                    Degree type inactive
                </a></li>
            {% endif %}
        {% endif %}
    </ul>
</div>
"""

_active = \
"""
{% if p.active %}
    <span class="label label-success"><i class="fa fa-check"></i> Active</span>
{% else %}
    <span class="label label-warning"><i class="fa fa-times"></i> Inactive</span>
{% endif %}
"""


def degree_programmes_data(programmes):

    data = [{'name': p.name,
             'type': p.degree_type.name,
             'active': render_template_string(_active, p=p),
             'menu': render_template_string(_programmes_menu, programme=p)} for p in programmes]

    return jsonify(data)
