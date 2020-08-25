#
# Created by David Seery on 05/06/2018.
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
        <a class="dropdown-item" href="{{ url_for('admin.edit_skill', id=skill.id) }}">
            <i class="fas fa-pencil"></i> Edit details...
        </a>

        {% if skill.group is not none and skill.group.active %}
            {% if skill.active %}
                <a class="dropdown-item" href="{{ url_for('admin.deactivate_skill', id=skill.id) }}">
                    <i class="fas fa-wrench"></i> Make inactive
                </a>
            {% else %}
                <a class="dropdown-item" href="{{ url_for('admin.activate_skill', id=skill.id) }}">
                    <i class="fas fa-wrench"></i> Make active
                </a>
            {% endif %}
        {% else %}
            <a class="dropdown-item disabled">Parent disabled</a>
        {% endif %}
    </ul>
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


def skills_data(skills):

    data = [{'name': s.name,
             'group': s.group.make_label() if s.group is not None else '<span class="badge badge-secondary">None</span>',
             'active': render_template_string(_active, a=s),
             'menu': render_template_string(_menu, skill=s)} for s in skills]

    return jsonify(data)
