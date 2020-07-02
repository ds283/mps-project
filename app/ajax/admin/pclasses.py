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


_programmes = \
"""
{% for programme in pcl.programmes %}
    {{ programme.short_label|safe }}
{% endfor %}
"""

_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <li class="dropdown-header">Edit</li>
        
        <li>
            <a href="{{ url_for('admin.edit_pclass', id=pcl.id) }}">
                <i class="fa fa-cogs"></i> Settings...
            </a>
        </li>
        <li>
            <a href="{{ url_for('admin.edit_pclass_text', id=pcl.id) }}">
                <i class="fa fa-pencil"></i> Customize messages...
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
                    <i class="fa fa-ban"></i> Can't make active
                </a></li>
            {% endif %}
        {% endif %}
        {% if pcl.publish %}
            <li><a href="{{ url_for('admin.unpublish_pclass', id=pcl.id) }}">
                <i class="fa fa-wrench"></i> Unpublish
            </a></li>
        {% else %}
            {% if pcl.available %}
                <li><a href="{{ url_for('admin.publish_pclass', id=pcl.id) }}">
                    <i class="fa fa-wrench"></i> Publish
                </a></li>
            {% else %}
                <li class="disabled"><a>
                    <i class="fa fa-ban"></i> Can't publish
                </a></li>
            {% endif %}
        {% endif %}
    </ul>
</div>
"""

_options = \
"""
{% if p.colour and p.colour is not none %}
  {{ p.make_label(p.colour)|safe }}
{% else %}
  <span class="badge badge-secondary">None</span>'
{% endif %}
{% if p.do_matching %}
    <span class="badge badge-secondary">Auto-match</span>
{% endif %}
{% if p.require_confirm %}
    <span class="badge badge-secondary">Confirm</span>
{% endif %}
{% if p.supervisor_carryover %}
    <span class="badge badge-secondary">Carryover</span>
{% endif %}
{% if p.include_available %}
    <span class="badge badge-secondary">Availability</span>
{% endif %}
{% if p.reenroll_supervisors_early %}
    <span class="badge badge-secondary">Re-enroll early</span>
{% endif %}
"""

_workload = \
"""
{% if p.uses_supervisor %}
    <span class="badge badge-primary">S {{ p.CATS_supervision }}</span>
{% endif %}
{% if p.uses_marker %}
    <span class="badge badge-info">M {{ p.CATS_marking }}</span>
{% endif %}
{% if p.uses_presentations %}
    <span class="badge badge-info">P {{ p.CATS_presentation }}</span>
{% endif %}
"""

_popularity = \
"""
{% set hourly_pl = 's' %}
{% if p.keep_hourly_popularity == 1 %}{% set hourly_pl = '' %}{% endif %}
{% set daily_pl = 's' %}
{% if p.keep_daily_popularity == 1 %}{% set daily_pl = '' %}{% endif %}
<span class="badge badge-secondary">Hourly: {{ p.keep_hourly_popularity }} day{{ hourly_pl }}</span>
<span class="badge badge-secondary">Daily: {{ p.keep_daily_popularity }} week{{ daily_pl }}</span>
"""

_personnel = \
"""
<div class="personnel-container">
    {% if p.coconvenors.first() %}
        <div>Convenors</div>
    {% else %}
        <div>Convenor</div>
    {% endif %}
    {% set style = p.make_CSS_style() %}
    <a class="badge badge-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ p.convenor_email }}">
        {{ p.convenor_name }}
    </a>
    {% for fac in p.coconvenors %}
        <a class="badge badge-secondary" href="mailto:{{ fac.user.email }}">
            {{ fac.user.name }}
        </a>
    {% endfor %}
</div>
{% if p.office_contacts.first() %}
    <div class="personnel-container">
        <div>Office contacts</div>
        {% for user in p.office_contacts %}
            <a class="badge badge-info" href="mailto:{{ user.email }}">
                {{ user.name }}
            </a>
        {% endfor %}
    </div>
{% endif %}
"""

_submissions = \
"""
<span class="badge badge-primary">{{ p.submissions }}/yr</span>
{% if p.uses_marker %}
    <span class="badge badge-info">2nd marked</span>
{% endif %}
{% if p.uses_presentations %}
    {% for item in p.periods.all() %}
        {% if item.has_presentation %}
            <span class="badge badge-info">Presentation: Prd #{{ item.period }}</span>
        {% endif %}
    {% endfor %}
{% endif %}
"""


_timing = \
"""
{% if p.start_level is not none %}
    <span class="badge badge-primary">Y{{ p.start_level.academic_year }}</span>
{% else %}
    <span class="badge badge-danger">Start level missing</span>
{% endif %}
<span class="badge badge-secondary">extent: {{ p.extent }} yr</span>
{% if p.selection_open_to_all %}
    <span class="badge badge-secondary">enroll: open</span>
{% else %}
    <span class="badge badge-secondary">enroll: degree</span>
{% endif %}
{% if p.auto_enroll_years == p.AUTO_ENROLL_PREVIOUS_YEAR %}
    <span class="badge badge-secondary">enroll: prev</span>
{% elif p.auto_enroll_years == p.AUTO_ENROLL_ANY_YEAR %}
    <span class="badge badge-secondary">enroll: any</span>
{% else %}
    <span class="badge badge-danger">enroll: unknown</span>
{% endif %}
"""


_name = \
"""
{{ p.name }} {{ p.make_label(p.abbreviation)|safe }}
<div>
{% if p.active %}
    <span class="badge badge-success"><i class="fa fa-check"></i> Active</span>
{% else %}
    <span class="badge badge-warning"><i class="fa fa-times"></i> Inactive</span>
{% endif %}
{% if p.publish %}
    <span class="badge badge-success"><i class="fa fa-eye"></i> Published</span>
{% else %}
    <span class="badge badge-warning"><i class="fa fa-eye-slash"></i> Unpublished</span>
{% endif %}
</div>
"""


def pclasses_data(classes):
    data = [{'name': render_template_string(_name, p=p),
             'options': render_template_string(_options, p=p),
             'timing': render_template_string(_timing, p=p),
             'cats': render_template_string(_workload, p=p),
             'submissions': render_template_string(_submissions, p=p),
             'popularity': render_template_string(_popularity, p=p),
             'personnel': render_template_string(_personnel, p=p),
             'programmes': render_template_string(_programmes, pcl=p),
             'menu': render_template_string(_menu, pcl=p)} for p in classes]

    return jsonify(data)
