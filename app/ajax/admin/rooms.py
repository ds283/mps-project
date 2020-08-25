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
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <a class="dropdown-item" href="{{ url_for('admin.edit_room', id=r.id) }}">
            <i class="fas fa-pencil"></i> Edit details...
        </a>

        {% if r.active %}
            <a class="dropdown-item" href="{{ url_for('admin.deactivate_room', id=r.id) }}">
                <i class="fas fa-wrench"></i> Make inactive
            </a>
        {% else %}
            {% if r.available %}
                <a class="dropdown-item" href="{{ url_for('admin.activate_room', id=r.id) }}">
                    <i class="fas fa-wrench"></i> Make active
                </a>
            {% else %}
                <a class="dropdown-item disabled">
                    <i class="fas fa-ban"></i> Building inactive
                </a>
            {% endif %}
        {% endif %}
    </div>
</div>
"""


_active = \
"""
{% if r.active %}
    <span class="badge badge-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge badge-warning"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""


_info = \
"""
<span class="badge badge-primary">Capacity {{ r.capacity }}</span>
{% if r.lecture_capture %}
    <span class="badge badge-info">Lecture capture</span>
{% endif %}
"""


def rooms_data(rooms):

    data = [{'name': r.name,
             'building': r.building.make_label(),
             'info': render_template_string(_info, r=r),
             'active': render_template_string(_active, r=r),
             'menu': render_template_string(_menu, r=r)} for r in rooms]

    return jsonify(data)
