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
_types_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_level', id=l.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit details...
        </a>

        {% if l.active %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_level', id=l.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_level', id=l.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make active
            </a>
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_status = """
{% if l.active %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""


# language=jinja2
_colour = """
{% if l.colour %}
    {{ simple_label(l.make_label(l.colour)) }}
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""


def FHEQ_levels_data(levels):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [
        {
            "name": l.name,
            "short_name": l.short_name,
            "numeric_level": "{n}".format(n=l.numeric_level),
            "colour": render_template_string(_colour, l=l, simple_label=simple_label),
            "status": render_template_string(_status, l=l),
            "menu": render_template_string(_types_menu, l=l),
        }
        for l in levels
    ]

    return data
