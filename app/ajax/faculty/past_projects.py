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
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <a class="dropdown-item" href="{{ url_for('faculty.live_project', pid=project.id, text='offered projects view', url=url_for('faculty.past_projects')) }}">
            View web page
        </a>
    </div>
</div>
"""

_pclass = \
"""
{% set style = config.project_class.make_CSS_style() %}
<a class="badge badge-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ config.convenor_email }}">
    {{ config.project_class.abbreviation }} ({{ config.convenor_name }})
</a>
"""


_name = \
"""
{% from "faculty/macros.html" import project_metadata %}
<a href="{{ url_for('faculty.live_project', pid=p.id, text='offered projects view', url=url_for('faculty.past_projects')) }}">
    {{ p.name }}
</a>
<div>
    {{ project_metadata(p) }}
</div>
"""


_metadata = \
"""
{% from "faculty/macros.html" import project_selection_data, project_rank_data %}
<div>
    {{ project_selection_data(p) }}
</div>
<div style="margin-top: 6px;">
    {{ project_rank_data(p, url_for('faculty.past_projects'), text='past projects view', live=false) }}
</div>
"""


def pastproject_data(projects):
    data = [{'year': '{c}'.format(c=p.config.year),
             'name': render_template_string(_name, p=p),
             'pclass': render_template_string(_pclass, config=p.config),
             'group': p.group.make_label(),
             'metadata': render_template_string(_metadata, p=p),
             'students': 'Not yet implemented',
             'menu': render_template_string(_project_menu, project=p)} for p in projects]

    return jsonify(data)
