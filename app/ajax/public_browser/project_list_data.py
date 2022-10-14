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
_group = \
"""
<a class="badge bg-secondary text-decoration-none" style="{{ group.make_CSS_style() }}">{{ group.name }}</a>
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

def _project_list_data(p: Project):
    return {'name': '<a class="text-decoration-none" href="#">{name}</a>'.format(name=p.name),
            'supervisor': '{name}'.format(name=p.owner.user.name),
            'group': render_template_string(_group, group=p.group),
            'skills': render_template_string(_skills, skills=p.ordered_skills)}


def public_browser_project_list(projects: List[Project]):
    return [_project_list_data(p) for p in projects]
