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


_groups_menu = \
"""
<div class="dropdown">
    <button class="btn btn-success btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('admin.edit_group', id=group.id) }}">
                <i class="fa fa-pencil"></i> Edit details
            </a>
        </li>

        <li>
            {% if group.active %}
                <a href="{{ url_for('admin.deactivate_group', id=group.id) }}">
                    Make inactive
                </a>
            {% else %}
                <a href="{{ url_for('admin.activate_group', id=group.id) }}">
                    Make active
                </a>
            {% endif %}
        </li>
    </ul>
</div>
"""


def groups_data(groups):

    data = []

    for group in groups:
        data.append({ 'abbrv': group.abbreviation,
                      'active': 'Active' if group.active else 'Inactive',
                      'name': group.name,
                      'website': '<a href="http://{web}">{web}</a>'.format(web=group.website) if group.website is not None
                            else '<span class="label label-default">None</span>',
                      'menu': render_template_string(_groups_menu, group=group)
                    })

    return jsonify(data)
