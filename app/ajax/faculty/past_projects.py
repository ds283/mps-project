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


# language=jinja2
_project_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('faculty.live_project', pid=project.id, text='offered projects view', url=url_for('faculty.past_projects')) }}">
            View web page
        </a>
    </div>
</div>
"""

# language=jinja2
_pclass = \
"""
{% set style = config.project_class.make_CSS_style() %}
<a class="badge text-decoration-none bg-info text-dark" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ config.convenor_email }}">
    {{ config.project_class.abbreviation }} ({{ config.convenor_name }})
</a>
"""


# language=jinja2
_name = \
"""
{% from "faculty/macros.html" import project_metadata %}
<a class="text-decoration-none" href="{{ url_for('faculty.live_project', pid=p.id, text='offered projects view', url=url_for('faculty.past_projects')) }}">
    {{ p.name }}
</a>
<div>
    {{ project_metadata(p) }}
</div>
"""


# language=jinja2
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
