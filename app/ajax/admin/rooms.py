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


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_room', id=r.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit details...
        </a>

        {% if r.active %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_room', id=r.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            {% if r.available %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_room', id=r.id) }}">
                    <i class="fas fa-wrench fa-fw"></i> Make active
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2 disabled">
                    <i class="fas fa-ban fa-fw"></i> Building inactive
                </a>
            {% endif %}
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_active = \
"""
{% if r.active %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""


# language=jinja2
_info = \
"""
<span class="badge bg-primary">Capacity {{ r.capacity }}</span>
<span class="badge bg-info">Max occupancy {{ r.maximum_occupancy }}</span>
{% if r.lecture_capture %}
    <span class="badge bg-info">Lecture capture</span>
{% endif %}
"""


def rooms_data(rooms):

    data = [{'name': r.name,
             'building': r.building.make_label(),
             'info': render_template_string(_info, r=r),
             'active': render_template_string(_active, r=r),
             'menu': render_template_string(_menu, r=r)} for r in rooms]

    return jsonify(data)
