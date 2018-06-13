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


_project_name = \
"""
{% set offerable = project.offerable %}
<div class="{% if not offerable %}has-error{% endif %}">
    <a href="{{ url_for('faculty.project_preview', id=project.id) }}">
        <strong>{{ project.name }}</strong>
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
        <span class="label label-success">Project active</span>
    {% else %}
        <span class="label label-warning">Project active</span>
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
    <a class="btn btn-info btn-block btn-sm {% if loop.index > 1 %}btn-table-block{% endif %}" href="mailto:{{ pclass.convenor.email }}">
        {{ pclass.abbreviation }} ({{ pclass.convenor.build_name() }})
    </a>
{% endfor %}
"""

_project_meetingreqd = \
"""
{% if project.meeting_reqd == 1 %}
    Required
{% elif project.meeting_reqd == 2 %}
    Optional
{% elif project.meeting_reqd == 3 %}
    No
{% else %}
    Unknown
{% endif %}
"""

_project_prefer = \
"""
{% for programme in project.programmes %}
    {% if programme.active %}
        <span class="label label-default">{{ programme.name }} {{ programme.degree_type.name }}</span>
    {% endif %}
{% endfor %}
"""

_project_skills = \
"""
{% for skill in project.skills %}
    {% if skill.active %}
        <span class="label label-default">{{ skill.name }}</span>
    {% endif %}
{% endfor %}
"""


def build_data(projects, menu_template, config=None):

    # filter list of projects for current user
    data = [{'name': render_template_string(_project_name, project=p),
             'owner': '<a href="mailto:{em}">{nm}</a>'.format(em=p.owner.email, nm=p.owner.build_name()),
             'status': render_template_string(_project_status, project=p, enrollment=e),
             'pclasses': render_template_string(_project_pclasses, project=p),
             'meeting': render_template_string(_project_meetingreqd, project=p),
             'group': '<span class="label label-success">{gp}</span>'.format(gp=p.group.abbreviation),
             'prefer': render_template_string(_project_prefer, project=p),
             'skills': render_template_string(_project_skills, project=p),
             'menu': render_template_string(menu_template, project=p, config=config)} for p, e in projects]

    return jsonify(data)
