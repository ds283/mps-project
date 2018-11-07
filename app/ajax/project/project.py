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
{% set offerable = project.is_offerable %}
<a href="{{ url_for('faculty.project_preview', id=project.id, text=text, url=url) }}">
    {{ project.name }}
    {% if not offerable %}
        <i class="fa fa-exclamation-triangle" style="color:red;"></i>
    {% endif %}
</a>
{% if name_labels %}
    <p></p>
    {% for pclass in project.project_classes %}
        {% if pclass.active %}
            {% set style = pclass.make_CSS_style() %}
            <a class="label label-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor_email }}">{{ pclass.abbreviation }}</a>
        {% endif %}
    {% else %}
        <span class="label label-danger">No project classes</span>
    {% endfor %}
{% endif %}
{% if not offerable %}
    <p></p>
    {% set errors = project.errors %}
    {% set warnings = project.warnings %}
    {% if errors|length == 1 %}
        <span class="label label-danger">1 error</span>
    {% elif errors|length > 1 %}
        <span class="label label-danger">{{ errors|length }} errors</span>
    {% else %}
        <span class="label label-success">0 errors</span>
    {% endif %}
    {% if warnings|length == 1 %}
        <span class="label label-warning">1 warning</span>
    {% elif warnings|length > 1 %}
        <span class="label label-warning">{{ warnings|length }} warnings</span>
    {% else %}
        <span class="label label-success">0 warnings</span>
    {% endif %}
    {% if errors|length > 0 %}
        <div class="has-error">
            {% for item in errors %}
                {% if loop.index <= 5 %}
                    <p class="help-block">{{ item }}</p>
                {% elif loop.index == 6 %}
                    <p class="help-block">...</p>
                {% endif %}            
            {% endfor %}
        </div>
    {% endif %}
    {% if warnings|length > 0 %}
        <div class="has-error">
            {% for item in warnings %}
                {% if loop.index <= 5 %}
                    <p class="help-block">Warning: {{ item }}</p>
                {% elif loop.index == 6 %}
                    <p class="help-block">...</p>
                {% endif %}
            {% endfor %}
        </div>
    {% endif %}
{% endif %}
"""

_project_status = \
"""
{% if project.is_offerable %}
    {% if project.active %}
        <span class="label label-success"><i class="fa fa-check"></i> Project active</span>
    {% else %}
        <span class="label label-warning"><i class="fa fa-times"></i> Project inactive</span>
    {% endif %}
    {% if enrollment and enrollment is not none %}
        {{ enrollment.supervisor_label|safe }}
    {% endif %}
{% else %}
    <span class="label label-danger">Not available</span>
{% endif %}
"""

_project_pclasses = \
"""
{% for pclass in project.project_classes %}
    {% set style = pclass.make_CSS_style() %}
    <a class="label label-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor_email }}">{{ pclass.abbreviation }} ({{ pclass.convenor_name }})</a>
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
{% for programme in project.ordered_programmes %}
    {% if programme.active %}
        {{ programme.short_label|safe }}
    {% endif %}
{% endfor %}
"""

_project_skills = \
"""
{% for skill in skills %}
    {% if skill.is_active %}
      {{ skill.short_label|safe }}
    {% endif %}
{% endfor %}
"""


def build_data(projects, menu_template, config=None, text=None, url=None, name_labels=False):

    data = [{'name': render_template_string(_project_name, project=p, text=text, url=url, name_labels=name_labels),
             'owner': {
                 'display': '<a href="mailto:{em}">{nm}</a>'.format(em=p.owner.user.email, nm=p.owner.user.name),
                 'sortvalue': p.owner.user.last_name + p.owner.user.first_name},
             'status': render_template_string(_project_status, project=p, enrollment=e),
             'pclasses': render_template_string(_project_pclasses, project=p),
             'meeting': render_template_string(_project_meetingreqd, project=p),
             'group': p.group.make_label(),
             'prefer': render_template_string(_project_prefer, project=p),
             'skills': render_template_string(_project_skills, skills=p.ordered_skills),
             'menu': render_template_string(menu_template, project=p, config=config, text=text, url=url)} for p, e in projects]

    return jsonify(data)
