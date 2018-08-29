#
# Created by David Seery on 12/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for


_project_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('faculty.live_project', pid=project.id, text='offered projects view', url=url_for('faculty.past_projects')) }}">
                View web page
            </a>
        </li>
    </ul>
</div>
"""

_pclass = \
"""
{% set style = config.project_class.make_CSS_style() %}
<a class="label label-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ config.convenor_email }}">
    {{ config.project_class.abbreviation }} ({{ config.convenor_name }})
</a>
"""


def pastproject_data(projects):

    data = [{'year': '{c}'.format(c=p.config.year),
             'name': '<a href="{url}">{name}</a>'.format(name=p.name, url=url_for('faculty.live_project',
                                                                                  pid=p.id,
                                                                                  text='offered projects view',
                                                                                  url=url_for('faculty.past_projects'))),
             'pclass': render_template_string(_pclass, config=p.config),
             'group': p.group.make_label(),
             'metadata': render_template_string('{% from "faculty/macros.html" import project_metadata %}{{ project_metadata(p) }}', p=p),
             'students': 'Not yet implemented',
             'menu': render_template_string(_project_menu, project=p)} for p in projects]

    return jsonify(data)
