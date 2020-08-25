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
        <a class="dropdown-item" href="{{ url_for('admin.edit_skill_group', id=group.id) }}">
            <i class="fas fa-pencil"></i> Edit details...
        </a>

        {% if group.active %}
            <a class="dropdown-item" href="{{ url_for('admin.deactivate_skill_group', id=group.id) }}">
                <i class="fas fa-wrench"></i> Make inactive
            </a>
        {% else %}
            <a class="dropdown-item" href="{{ url_for('admin.activate_skill_group', id=group.id) }}">
                <i class="fas fa-wrench"></i> Make active
            </a>
        {% endif %}
    </div>
</div>
"""


_active = \
"""
{% if a.active %}
    <span class="badge badge-success"><i class="fas fa-check"></i> Active</span>
{% else %}
    <span class="badge badge-warning"><i class="fas fa-times"></i> Inactive</span>
{% endif %}
"""


_include_name = \
"""
{% if g.add_group %}
    <span class="badge badge-success"><i class="fas fa-check"></i> Yes</span>
{% else %}
    <span class="badge badge-secondary"><i class="fas fa-times"></i> No</span>
{% endif %}
"""


def skill_groups_data(groups):

    data = [{'name': g.name,
             'colour': g.make_label(g.colour),
             'active': render_template_string(_active, a=g),
             'include': render_template_string(_include_name, g=g),
             'menu': render_template_string(_menu, group=g)} for g in groups]

    return jsonify(data)
