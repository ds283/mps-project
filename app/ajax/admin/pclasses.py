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
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
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

    data = [{'name': '{name} ({ab})'.format(name=p.name, ab=p.abbreviation),
             'active': 'Active' if p.active else 'Inactive',
             'colour': '<span class="label label-default">None</span>' if p.colour is None else p.make_label(p.colour),
             'year': 'Y{yr}'.format(yr=p.year),
             'extent': '{ex}'.format(ex=p.extent),
             'submissions': '{sub}'.format(sub=p.submissions),
             'convenor': '{n} <a href="mailto:{em}>{em}</a>'.format(n=p.convenor.build_name(), em=p.convenor.email),
             'programmes': render_template_string(_pclasses_programmes, pcl=p),
             'menu': render_template_string(_pclasses_menu, pcl=p)} for p in classes]

    return jsonify(data)
