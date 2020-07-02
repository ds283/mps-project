#
# Created by David Seery on 2018-09-27.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_presentation = \
"""
{% if p.has_presentation %}
    <span class="badge badge-success"><i class="fa fa-check"></i> Required</span>
    {% if p.collect_presentation_feedback %}
        <span class="badge badge-success"><i class="fa fa-check"></i> Collect feedback</span>
    {% else %}
        <span class="badge badge-warning"><i class="fa fa-times"></i> Do not collect feedback</span>
    {% endif %}
    <span class="badge badge-primary">Assessors per group = {{ p.number_assessors }}</span>
    <span class="badge badge-primary">Max group size = {{ p.max_group_size }}</span> 
    {% if p.lecture_capture %}
        <span class="badge badge-info">Requires lecture capture</span>
    {% else %}
        <span class="badge badge-default">Lecture capture not required</span>
    {% endif %}
    <p></p>
    <span class="badge badge-info">Morning: {{ p.morning_session }}</span>
    <span class="badge badge-info">Afternoon: {{ p.afternoon_session }}</span>
    <span class="badge badge-info">Format: {{ p.talk_format }}</span>
{% else %}
    <span class="badge badge-default">Not required</span>
{% endif %}
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('admin.edit_period', id=period.id) }}">
                <i class="fa fa-cogs"></i> Edit period...
            </a>
        </li>
        <li>
            <a href="{{ url_for('admin.delete_period', id=period.id) }}">
                <i class="fa fa-trash"></i> Delete period
            </a>
        </li>
    </ul>
</div>
"""


_name = \
"""
{% if p.name %}
    {{ p.name }}
{% else %}
    <span class="badge badge-default">None</span>
{% endif %}
{% if p.start_date %}
    <div>
        <span class="badge badge-info">Start: {{ p.start_date.strftime("%a %d %b %Y") }}</span>
    </div>
{% endif %}
{% if p.collect_project_feedback %}
    <div>
        <span class="badge badge-info"><i class="fa fa-check"></i> Collect feedback</span>
    </div>
{% endif %}  
"""


def periods_data(periods):

    data = [{'number': p.period,
             'name': render_template_string(_name, p=p),
             'presentation': render_template_string(_presentation, p=p),
             'menu': render_template_string(_menu, period=p)} for p in periods]

    return jsonify(data)
