#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, get_template_attribute

# language=jinja2
_supervisors_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_supervisor', id=role.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit details...
        </a>

        {% if role.active %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_supervisor', id=role.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_supervisor', id=role.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make active
            </a>
        {% endif %}
    </ul>
</div>
"""


# language=jinja2
_active = """
{% if r.active %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""


# language=jinja2
_colour = """
{{ simple_label(r.make_label(r.colour)) }}
"""


# language=jinja2
_name = """
{{ r.name }} {{ simple_label(r.make_label()) }}
"""


def supervisors_data(roles):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [
        {
            "role": render_template_string(_name, r=r, simple_label=simple_label),
            "colour": render_template_string(_colour, r=r, simple_label=simple_label),
            "active": render_template_string(_active, r=r),
            "menu": render_template_string(_supervisors_menu, role=r),
        }
        for r in roles
    ]

    return data
