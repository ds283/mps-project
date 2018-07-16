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
    {{ programme.label()|safe }}
{% endfor %}
"""

_pclasses_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('admin.edit_pclass', id=pcl.id) }}">
                <i class="fa fa-pencil"></i> Edit project class
            </a>
        </li>

        {% if pcl.active %}
            <li><a href="{{ url_for('admin.deactivate_pclass', id=pcl.id) }}">
                Make inactive
            </a></li>
        {% else %}
            {% if pcl.available() %}
                <li><a href="{{ url_for('admin.activate_pclass', id=pcl.id) }}">
                    Make active
                </a></li>
            {% else %}
                <li class="disabled"><a>
                    Programmes inactive
                </a>
                </li>
            {% endif %}
        {% endif %}
    </ul>
</div>
"""

_active = \
"""
{% if p.active %}
    <span class="label label-success"><i class="fa fa-check"></i> Active</span>
{% else %}
    <span class="label label-warning"><i class="fa fa-times"></i> Inactive</span>
{% endif %}
"""

_workload = \
"""
<span class="label label-info">{{ p.CATS_supervision }}</span>
/
<span class="label label-default">{{ p.CATS_marking }}</span>
"""

_popularity = \
"""
{% set hourly_pl = 's' %}
{% if p.keep_hourly_popularity == 1 %}{% set hourly_pl = '' %}{% endif %}
{% set daily_pl = 's' %}
{% if p.keep_daily_popularity == 1 %}{% set daily_pl = '' %}{% endif %}
<span class="label label-info">{{ p.keep_hourly_popularity }} day{{ hourly_pl }}</span>
/
<span class="label label-info">{{ p.keep_daily_popularity }} week{{ daily_pl }}</span>
"""

_convenor = \
"""
{% set style = p.make_CSS_style() %}
<a class="label label-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ p.convenor.email }}">
    {{ p.convenor.build_name() }}
</a>
"""


def pclasses_data(classes):

    data = [{'name': '{name} ({ab})'.format(name=p.name, ab=p.abbreviation),
             'active': render_template_string(_active, p=p),
             'colour': '<span class="label label-default">None</span>' if p.colour is None else p.make_label(p.colour),
             'year': '<span class="label label-info">Y{yr}</span>'.format(yr=p.year),
             'extent': '<span class="label label-info">{ex}</span>'.format(ex=p.extent),
             'cats': render_template_string(_workload, p=p),
             'submissions': '<span class="label label-primary">{sub}</span>'.format(sub=p.submissions),
             'popularity': render_template_string(_popularity, p=p),
             'convenor': render_template_string(_convenor, p=p),
             'programmes': render_template_string(_pclasses_programmes, pcl=p),
             'menu': render_template_string(_pclasses_menu, pcl=p)} for p in classes]

    return jsonify(data)
