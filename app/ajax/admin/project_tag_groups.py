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
_menu = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_project_tag_group', gid=group.id) }}">
            <i class="fas fa-pencil-alt fa-fw"></i> Edit details...
        </a>
        {% if group.active %}
            {% if not group.default %}
                <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.deactivate_project_tag_group', gid=group.id) }}">
                    <i class="fas fa-wrench fa-fw"></i> Make inactive
                </a>
            {% else %}
                <a class="dropdown-item d-flex gap-w disabled">
                    <i class="fas fa-wrench fa-fw"></i> Make inactive
                </a>
            {% endif %}
        {% else %}
            <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.activate_project_tag_group', gid=group.id) }}">
                <i class="fas fa-wrench fa-fw"></i> Make active
            </a>
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_active = """
{% if g.active %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""


# language=jinja2
_include_name = """
{% if g.add_group %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Yes</span>
{% else %}
    <span class="badge bg-secondary"><i class="fas fa-times"></i> No</span>
{% endif %}
"""


# language=jinja2
_name = """
{{ g.name }}
{% if g.default %}
    <span class="badge bg-success">Default</span>
{% endif %}
"""


def tag_groups_data(groups):
    data = [
        {
            "name": render_template_string(_name, g=g),
            "active": render_template_string(_active, g=g),
            "include": render_template_string(_include_name, g=g),
            "menu": render_template_string(_menu, group=g),
        }
        for g in groups
    ]

    return data
