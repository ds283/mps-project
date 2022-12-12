#
# Created by David Seery on 12/12/2022.
# Copyright (c) 2022 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_project_tag', tid=tag.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit details...
        </a>
        {% if tag.group is not none and tag.group.active %}
            {% if tag.active %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_project_tag', tid=tag.id) }}">
                    <i class="fas fa-wrench fa-fw"></i> Make inactive
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_project_tag', tid=tag.id) }}">
                    <i class="fas fa-wrench fa-fw"></i> Make active
                </a>
            {% endif %}
        {% else %}
            <a class="dropdown-item d-flex gap-2 disabled">Parent disabled</a>
        {% endif %}
    </ul>
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
_group = \
"""
{% if t.group %}
    <span class="badge bg-secondary">{{ t.group.name }}</span>
{% else %}
    <span class="badge bg-danger">None</span>
{% endif %}
"""


def tags_data(tags):
    data = [{'name': t.name,
             'colour': '<span class="badge bg-secondary">None</span>' if t.colour is None else t.make_label(text=t.colour),
             'group': render_template_string(_group, t=t),
             'active': render_template_string(_active, t=t),
             'menu': render_template_string(_menu, tag=t)} for t in tags]

    return data
