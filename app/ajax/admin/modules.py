#
# Created by David Seery on 2018-10-26.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, render_template_string


_code = \
"""
<a href="{{ url_for('admin.edit_module', id=m.id) }}">{{ m.code }}</span>
"""


_status = \
"""
{% if m.active %}
    <span class="label label-success"><i class="fa fa-check"></i> Active</span>
    <span class="label label-info">First taught {{ m.first_taught }}</span>
{% else %}
    <span class="label label-default"><i class="fa fa-times"></i> Retired</span>
    <span class="label label-info">First taught {{ m.first_taught }}</span>
    <span class="label label-info">Last taught {{ m.last_taught }}</span>
{% endif %}
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        {% set disabled = not m.active %}
        <li {% if disabled %}class="disabled"{% endif %}>
            <a {% if not disabled %}href="{{ url_for('admin.edit_module', id=m.id) }}"{% endif %}>
                <i class="fa fa-pencil"></i> Edit details
            </a>
        </li>

        {% if m.active %}
            <li><a href="{{ url_for('admin.retire_module', id=m.id) }}">
                <i class="fa fa-wrench"></i> Retire
            </a></li>
        {% else %}
            <li><a href="{{ url_for('admin.unretire_module', id=m.id) }}">
                <i class="fa fa-wrench"></i> Unretire
            </a></li>
        {% endif %}
    </ul>
</div>
"""


def modules_data(modules):
    data = [{'code': render_template_string(_code, m=m),
             'name': m.name,
             'runs_in': m.academic_year_label,
             'status': render_template_string(_status, m=m),
             'menu': render_template_string(_menu, m=m)} for m in modules]

    return jsonify(data)
