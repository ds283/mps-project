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


_pclasses_programmes = \
"""
{% for programme in pcl.programmes %}
    <span class="label label-default">{{ programme.name }} {{ programme.degree_type.name }}</span>
{% endfor %}
"""

_pclasses_menu = \
"""
<div class="dropdown">
    <button class="btn btn-success btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('admin.edit_pclass', id=pcl.id) }}">
                <i class="fa fa-pencil"></i> Edit project class
            </a>
        </li>

        {% if pcl.active %}
            <li><a href="{{ url_for('admin.deactivate_pclass', id=pcl.id) }}">
                Make inactive
            </a></li>
        {% else %}
            {% if pcl.available() %}
                <li><a href="{{ url_for('admin.activate_pclass', id=pcl.id) }}">
                    Make active
                </a></li>
            {% else %}
                <li class="disabled"><a>
                    Programmes inactive
                </a>
                </li>
            {% endif %}
        {% endif %}
    </ul>
</div>
"""


def pclasses_data(classes):

    data = []

    for pcl in classes:
        data.append({ 'name': '{name} ({ab})'.format(name=pcl.name, ab=pcl.abbreviation),
                      'active': 'Active' if pcl.active else 'Inactive',
                      'year': 'Y{yr}'.format(yr=pcl.year),
                      'extent': '{ex}'.format(ex=pcl.extent),
                      'submissions': '{sub}'.format(sub=pcl.submissions),
                      'convenor': '{n} <a href="mailto:{em}>{em}</a>'.format(n=pcl.convenor.build_name(),
                                                                             em=pcl.convenor.email),
                      'programmes': render_template_string(_pclasses_programmes, pcl=pcl),
                      'menu': render_template_string(_pclasses_menu, pcl=pcl)
                    })

    return jsonify(data)
