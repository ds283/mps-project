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


_cohort = \
"""
{{ sub.student.programme.label|safe }}
{{ sub.student.cohort_label|safe }}
{{ sub.academic_year_label|safe }}
"""


_published = \
"""
"""


_projects = \
"""
{% macro project_tag(r, show_period) %}
    {% set pclass = r.owner.config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    <div class="assignment-label" style="display: inline-block;">
        <span class="label {% if style %}label-default{% else %}label-info{% endif %}" {% if style %}style="{{ style }}"{% endif %}>{% if show_period %}#{{ r.submission_period }}: {% endif %}
            {{ r.supervisor.user.name }} (No. {{ r.project.number }})</span>
    </div>
{% endmacro %}
{% set recs = sub.ordered_assignments.all() %}
{% if recs|length == 1 %}
    {{ project_tag(recs[0], false) }}
{% elif recs|length > 1 %}
    {% for rec in sub.ordered_assignments %}
        {{ project_tag(rec, true) }}
    {% endfor %}
{% else %}
    <span class="label label-danger">None</span>
{% endif %}
"""


_markers = \
"""
{% macro marker_tag(r, show_period) %}
    <div class="assignment-label" style="display: inline-block;">
        <span class="label label-default" >{% if show_period %}#{{ r.submission_period }}: {% endif %}
            {{ r.marker.user.name }}</span>
    </div>
{% endmacro %}
{% set recs = sub.ordered_assignments.all() %}
{% if recs|length == 1 %}
    {{ project_tag(recs[0], false) }}
{% elif recs|length > 1 %}
    {% for rec in sub.ordered_assignments %}
        {{ marker_tag(rec, true) }}
    {% endfor %}
{% else %}
    <span class="label label-danger">None</span>
{% endif %}
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        {% if sub.published %}
            <li>
                <a href="{{ url_for('convenor.unpublish_assignment', id=sub.id) }}">
                    <i class="fa fa-eye-slash"></i> Unpublish
                </a>
            </li>
        {% else %}
            <li>
                <a href="{{ url_for('convenor.publish_assignment', id=sub.id) }}">
                    <i class="fa fa-eye"></i> Publish to student
                </a>
            </li>
        {% endif %}
    </ul>
</div>
"""


_name = \
"""
<a href="mailto:{{ sub.student.user.email }}">{{ sub.student.user.name }}</a>
<div>
{% if sub.published %}
    <span class="label label-success"><i class="fa fa-eye"></i> Published</span>
{% else %}
    <span class="label label-warning"><i class="fa fa-eye-slash"></i> Unpublished</span>
{% endif %}
</div>
"""


def submitters_data(students, config):

    data = [{'name': {
                'display': render_template_string(_name, sub=s),
                'sortstring': s.student.user.last_name + s.student.user.first_name
             },
             'cohort': render_template_string(_cohort, sub=s),
             'projects': render_template_string(_projects, sub=s),
             'markers': render_template_string(_markers, sub=s),
             'menu': render_template_string(_menu, sub=s)} for s in students]

    return jsonify(data)
