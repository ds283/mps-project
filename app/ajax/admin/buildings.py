#
# Created by David Seery on 2018-10-02.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, get_template_attribute

# language=jinja2
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_building', id=b.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit details...
        </a>

        {% if b.active %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_building', id=b.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_building', id=b.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make active
            </a>
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_active = """
{% if b.active %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""


# language=jinja2
_colour = """
{{ simple_label(b.make_label(b.colour)) }}
"""


def buildings_data(buildings):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [
        {
            "name": b.name,
            "colour": render_template_string(_colour, b=b, simple_label=simple_label),
            "active": render_template_string(_active, b=b),
            "menu": render_template_string(_menu, b=b),
        }
        for b in buildings
    ]

    return jsonify(data)
