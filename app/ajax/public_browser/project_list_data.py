#
# Created by David Seery on 14/10/2022.
# Copyright (c) 2022 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import List

from flask import render_template_string

from ...models import Project

# language=jinja2
_name = \
"""
<a class="text-decoration-none" href="{{ url_for('public_browser.project', pclass_id=pclass_id, proj_id=project.id) }}">{{ project.name }}</a>
"""

# language=jinja2
_group = \
"""
{% set ns = namespace(affiliation=false) %}
{% if project.group %}
    <a {% if href %}href="{{ href }}"{% endif %} class="badge bg-secondary text-decoration-none" style="{{ group.make_CSS_style() }}">{{ project.group.name }}</a>
{% endif %}
{% for tag in project.forced_group_tags %}
    {{ tag.make_label()|safe }}
    {% set ns.affiliation = true %}
{% endfor %}
{% if not ns.affiliation %}
    <span class="badge bg-warning text-dark">No affiliations</span>
{% endif %}
"""

# language=jinja2
_skills = \
"""
{% for skill in skills %}
    {% if skill.is_active %}
        {% if skill.group is none %}
            {{ skill.make_label()|safe }}
        {% else %}
            <a class="badge bg-secondary text-decoration-none" style="{{ skill.group.make_CSS_style() }}">{%- if skill.group.add_group -%}{{ skill.group.name }}:{% endif %} {{ skill.name }}</a>
        {% endif %}
    {% endif %}
{% endfor %}
"""

def _project_list_data(pclass_id: int, p: Project):
    return {'name': render_template_string(_name, pclass_id=pclass_id, project=p),
            'supervisor': '{name}'.format(name=p.owner.user.name),
            'group': render_template_string(_group, project=p),
            'skills': render_template_string(_skills, skills=p.ordered_skills)}


def public_browser_project_list(pclass_id: int, projects: List[Project]):
    return [_project_list_data(pclass_id, p) for p in projects]
