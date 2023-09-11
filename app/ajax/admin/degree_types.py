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
_types_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_degree_type', id=type.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit details...
        </a>

        {% if type.active %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_degree_type', id=type.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_degree_type', id=type.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make active
            </a>
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_active = \
"""
{% if t.active %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""


# language=jinja2
_name = \
"""
{{ t.name }} {{ simple_label(t.make_label()) }}
"""


# language=jinja2
_duration = \
"""
{% set pl = 's' %}{% if t.duration == 1 %}{% set pl = '' %}{% endif %}
{{ t.duration }} year{{ pl }}
"""


# language=jinja2
_colour = \
"""
{{ simple_label(t.make_label(t.colour)) }}
"""


def degree_types_data(types):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [{'name': render_template_string(_name, t=t, simple_label=simple_label),
             'level': t._level_text(t.level),
             'duration': render_template_string(_duration, t=t),
             'active': render_template_string(_active, t=t),
             'colour': render_template_string(_colour, t=t, simple_label=simple_label),
             'menu': render_template_string(_types_menu, type=t)} for t in types]

    return data
