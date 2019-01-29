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


_pclasses_programmes = \
"""
{% for programme in pcl.programmes %}
    {{ programme.short_label|safe }}
{% endfor %}
"""

_pclasses_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li class="dropdown-header">Edit</li>
        
        <li>
            <a href="{{ url_for('admin.edit_pclass', id=pcl.id) }}">
                <i class="fa fa-cogs"></i> Settings...
            </a>
        </li>
        
        <li>
            <a href="{{ url_for('admin.edit_submission_periods', id=pcl.id) }}">
                <i class="fa fa-cogs"></i> Submission periods...
            </a>
        </li>
        
        <li role="separator" class="divider"></li>
        <li class="dropdown-header">Admin</a>

        {% if pcl.active %}
            <li><a href="{{ url_for('admin.deactivate_pclass', id=pcl.id) }}">
                <i class="fa fa-wrench"></i> Make inactive
            </a></li>
        {% else %}
            {% if pcl.available %}
                <li><a href="{{ url_for('admin.activate_pclass', id=pcl.id) }}">
                    <i class="fa fa-wrench"></i> Make active
                </a></li>
            {% else %}
                <li class="disabled"><a>
                    <i class="fa fa-ban"></i> Programmes inactive
                </a>
                </li>
            {% endif %}
        {% endif %}
    </ul>
</div>
"""

_status = \
"""
{% if p.active %}
    <span class="label label-success"><i class="fa fa-check"></i> Active</span>
{% else %}
    <span class="label label-warning"><i class="fa fa-times"></i> Inactive</span>
{% endif %}
{% if p.do_matching %}
    <span class="label label-default">Auto-match</span>
{% endif %}
{% if p.require_confirm %}
    <span class="label label-default">Confirm</span>
{% endif %}
{% if p.supervisor_carryover %}
     <span class="label label-default">Carryover</span>
{% endif %}
{% if p.reenroll_supervisors_early %}
    <span class="label label-default">Re-enroll early</span>
{% endif %}
"""

_workload = \
"""
{% if p.uses_supervisor %}
    <span class="label label-primary">Supv: {{ p.CATS_supervision }}</span>
{% endif %}
{% if p.uses_marker %}
    <span class="label label-info">Mark: {{ p.CATS_marking }}</span>
{% endif %}
{% if p.uses_presentations %}
    <span class="label label-info">Pres: {{ p.CATS_presentation }}</span>
{% endif %}
"""

_popularity = \
"""
{% set hourly_pl = 's' %}
{% if p.keep_hourly_popularity == 1 %}{% set hourly_pl = '' %}{% endif %}
{% set daily_pl = 's' %}
{% if p.keep_daily_popularity == 1 %}{% set daily_pl = '' %}{% endif %}
<span class="label label-default">Hourly: {{ p.keep_hourly_popularity }} day{{ hourly_pl }}</span>
<span class="label label-default">Daily: {{ p.keep_daily_popularity }} week{{ daily_pl }}</span>
"""

_convenor = \
"""
{% set style = p.make_CSS_style() %}
<a class="label label-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ p.convenor_email }}">
    {{ p.convenor_name }}
</a>
{% for fac in p.coconvenors %}
    <a class="label label-default" href="mailto:{{ fac.user.email }}">
        {{ fac.user.name }}
    </a>
{% endfor %}
"""

_submissions = \
"""
<span class="label label-primary">{{ p.submissions }}/yr</span>
{% if p.uses_marker %}
    <span class="label label-info">2nd marked</span>
{% endif %}
{% if p.uses_presentations %}
    {% for item in p.periods.all() %}
        {% if item.has_presentation %}
            <span class="label label-info">Presentation: Prd #{{ item.period }}</span>
        {% endif %}
    {% endfor %}
{% endif %}
"""

_configuration = \
"""
{% if p.start_level is not none %}
    <span class="label label-primary">Y{{ p.start_level.academic_year }}</span>
{% else %}
    <span class="label label-danger">Start level missing</span>
{% endif %}
<span class="label label-default">extent: {{ p.extent }} yr</span>
"""


def pclasses_data(classes):

    data = [{'name': '{name} {ab}'.format(name=p.name, ab=p.make_label(p.abbreviation)),
             'status': render_template_string(_status, p=p),
             'colour': '<span class="label label-default">None</span>' if p.colour is None else p.make_label(p.colour),
             'config': render_template_string(_configuration, p=p),
             'cats': render_template_string(_workload, p=p),
             'submissions': render_template_string(_submissions, p=p),
             'popularity': render_template_string(_popularity, p=p),
             'convenor': render_template_string(_convenor, p=p),
             'programmes': render_template_string(_pclasses_programmes, pcl=p),
             'menu': render_template_string(_pclasses_menu, pcl=p)} for p in classes]

    return jsonify(data)
