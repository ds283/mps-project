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

from ...models import TransferableSkill


_project_name = \
"""
{% set offerable = project.offerable %}
<div class="{% if not offerable %}has-error{% endif %}">
    <a href="{{ url_for('faculty.project_preview', id=project.id) }}">
        {{ project.name }}
    </a>
    {% if not offerable and project.error %}
        <p class="help-block">Warning: {{ project.error }}</p>
    {% endif %}
</div>
"""

_project_status = \
"""
{% if project.offerable %}
    {% if project.active %}
        <span class="label label-success"><i class="fa fa-check"></i> Project active</span>
    {% else %}
        <span class="label label-warning"><i class="fa fa-times"></i> Project inactive</span>
    {% endif %}
    {% if enrollment and enrollment is not none %}
        {{ enrollment.supervisor_label()|safe }}
    {% endif %}
{% else %}
    <span class="label label-danger">Not available</span>
{% endif %}
"""

_project_pclasses = \
"""
{% for pclass in project.project_classes %}
    {% set style = pclass.make_CSS_style() %}
    <a class="label label-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor.email }}">
        {{ pclass.abbreviation }} ({{ pclass.convenor.build_name() }})
    </a>
{% endfor %}
"""

_project_meetingreqd = \
"""
{% if project.meeting_reqd == project.MEETING_REQUIRED %}
    <span class="label label-danger">Required</span>
{% elif project.meeting_reqd == project.MEETING_OPTIONAL %}
    <span class="label label-warning">Optional</span>
{% elif project.meeting_reqd == project.MEETING_NONE %}
    <span class="label label-success">Not required</span>
{% else %}
    <span class="label label-default">Unknown</span>
{% endif %}
"""

_project_prefer = \
"""
{% for programme in project.programmes %}
    {% if programme.active %}
        {{ programme.label()|safe }}
    {% endif %}
{% endfor %}
"""

_project_skills = \
"""
{% for skill in skills %}
    {% if skill.is_active %}
      {{ skill.make_label()|safe }}
    {% endif %}
{% endfor %}
"""


def build_data(projects, menu_template, config=None):

    data = [{'name': render_template_string(_project_name, project=p),
             'owner': '<a href="mailto:{em}">{nm}</a>'.format(em=p.owner.email, nm=p.owner.build_name()),
             'status': render_template_string(_project_status, project=p, enrollment=e),
             'pclasses': render_template_string(_project_pclasses, project=p),
             'meeting': render_template_string(_project_meetingreqd, project=p),
             'group': p.group.make_label(),
             'prefer': render_template_string(_project_prefer, project=p),
             'skills': render_template_string(_project_skills, skills=p.ordered_skills),
             'menu': render_template_string(menu_template, project=p, config=config)} for p, e in projects]

    return jsonify(data)
