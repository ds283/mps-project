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

from flask import render_template_string, get_template_attribute

from ...models import Project

# language=jinja2
_name = """
<a class="text-decoration-none" href="{{ url_for('public_browser.project', pclass_id=pclass_id, proj_id=project.id) }}">{{ project.name }}</a>
"""

# language=jinja2
_owner = """
{% if not project.generic and project.owner is not none %}
    {{ project.owner.user.name }}
{% else %}
    <span class="badge bg-info">Generic</span>
{% endif %}
"""

# language=jinja2
_group = """
{% set ns = namespace(affiliation=false) %}
{% if project.group %}
    {{ simple_label(project.group.make_label()) }}
    {% set ns.affiliation = true %}
{% endif %}
{% for tag in project.forced_group_tags %}
    {{ simple_label(tag.make_label()) }}
    {% set ns.affiliation = true %}
{% endfor %}
{% if not ns.affiliation %}
    <span class="badge bg-warning text-dark">No affiliations</span>
{% endif %}
"""

# language=jinja2
_skills = """
{% for skill in skills %}
    {% if skill.is_active %}
        {% if skill.group is none %}
            {{ simple_label(skill.make_label()) }}
        {% else %}
            <a class="badge bg-secondary text-decoration-none" style="{{ skill.group.make_CSS_style() }}">{%- if skill.group.add_group -%}{{ skill.group.name }}:{% endif %} {{ skill.name }}</a>
        {% endif %}
    {% endif %}
{% endfor %}
"""


def _project_list_data(pclass_id: int, p: Project):
    simple_label = get_template_attribute("labels.html", "simple_label")

    return {
        "name": render_template_string(_name, pclass_id=pclass_id, project=p),
        "supervisor": render_template_string(_owner, project=p),
        "group": render_template_string(_group, project=p, simple_label=simple_label),
        "skills": render_template_string(_skills, skills=p.ordered_skills, simple_label=simple_label),
    }


def public_browser_project_list(pclass_id: int, projects: List[Project]):
    return [_project_list_data(pclass_id, p) for p in projects]
