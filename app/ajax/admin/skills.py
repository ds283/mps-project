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


_skills_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('admin.edit_skill', id=skill.id) }}">
                <i class="fa fa-pencil"></i> Edit details
            </a>
        </li>

        {% if skill.group is not none and skill.group.active %}
            {% if skill.active %}
                <li>
                    <a href="{{ url_for('admin.deactivate_skill', id=skill.id) }}">
                        Make inactive
                    </a>
                </li>
            {% else %}
                <li>
                    <a href="{{ url_for('admin.activate_skill', id=skill.id) }}">
                        Make active
                    </a>
                </li>
            {% endif %}
        {% else %}
            <li class="disabled">
                <a>Parent disabled</a>
            </li>
        {% endif %}
    </ul>
</div>
"""


_skill_group_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('admin.edit_skill_group', id=group.id) }}">
                <i class="fa fa-pencil"></i> Edit details
            </a>
        </li>

        <li>
            {% if group.active %}
                <a href="{{ url_for('admin.deactivate_skill_group', id=group.id) }}">
                    Make inactive
                </a>
            {% else %}
                <a href="{{ url_for('admin.activate_skill_group', id=group.id) }}">
                    Make active
                </a>
            {% endif %}
        </li>
    </ul>
</div>
"""


def skills_data(skills):

    data = [{'name': s.name,
             'group': s.group.make_label() if s.group is not None else '<span class="label label-default">None</span>',
             'active': 'Active' if s.active else 'Inactive',
             'menu': render_template_string(_skills_menu, skill=s)} for s in skills]

    return jsonify(data)


def skill_groups_data(groups):

    data = [{'name': g.name,
             'colour': g.make_label(g.colour),
             'active': 'Active' if g.active else 'Inactive',
             'include': 'Yes' if g.add_group else 'No',
             'menu': render_template_string(_skill_group_menu, group=g)} for g in groups]

    return jsonify(data)
