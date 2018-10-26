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
            <a href="{{ url_for('admin.edit_room', id=r.id) }}">
                <i class="fa fa-pencil"></i> Edit details
            </a>
        </li>

        {% if r.active %}
            <li><a href="{{ url_for('admin.deactivate_room', id=r.id) }}">
                <i class="fa fa-wrench"></i> Make inactive
            </a></li>
        {% else %}
            {% if r.available %}
                <li><a href="{{ url_for('admin.activate_room', id=r.id) }}">
                    <i class="fa fa-wrench"></i> Make active
                </a></li>
            {% else %}
                <li class="disabled"><a>
                    <i class="fa fa-ban"></i> Building inactive
                </a></li>
            {% endif %}
        {% endif %}
    </ul>
</div>
"""


_active = \
"""
{% if r.active %}
    <span class="label label-success"><i class="fa fa-check"></i> Active</span>
{% else %}
    <span class="label label-warning"><i class="fa fa-times"></i> Inactive</span>
{% endif %}
"""


_info = \
"""
<span class="label label-primary">Capacity {{ r.capacity }}</span>
{% if r.lecture_capture %}
    <span class="label label-info">Lecture capture</span>
{% endif %}
"""


def rooms_data(rooms):

    data = [{'name': r.name,
             'building': r.building.make_label(),
             'info': render_template_string(_info, r=r),
             'active': render_template_string(_active, r=r),
             'menu': render_template_string(_menu, r=r)} for r in rooms]

    return jsonify(data)
