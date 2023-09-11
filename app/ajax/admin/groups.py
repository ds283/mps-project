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
_groups_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_group', id=group.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit details...
        </a>

        {% if group.active %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_group', id=group.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_group', id=group.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make active
            </a>
        {% endif %}
    </div>
</div>
"""

# language=jinja2
_active = \
"""
{% if g.active %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""

# language=jinja2
_colour = \
"""
{% if g.colour %}
    {{ simple_label(g.make_label(g.colour)) }}
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""

# language=jinja2
_website = \
"""
{% if g.website %}
    <a class="text-decoration-none small" href="{{ g.website }}">{{ g.website }}</a>
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""


def groups_data(groups):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [{'abbrv': g.abbreviation,
             'active': render_template_string(_active, g=g),
             'name': g.name,
             'colour': render_template_string(_colour, g=g, simple_label=simple_label),
             'website': render_template_string(_website, g=g),
             'menu': render_template_string(_groups_menu, group=g)} for g in groups]

    return data
