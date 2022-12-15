#
# Created by David Seery on 2018-09-27.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import List

from flask import render_template_string, jsonify

from app.models import SubmissionPeriodDefinition

# language=jinja2
_presentation = \
"""
{% if p.has_presentation %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Required</span>
    {% if p.collect_presentation_feedback %}
        <span class="badge bg-success"><i class="fas fa-check"></i> Collect feedback</span>
    {% else %}
        <span class="badge bg-warning text-dark"><i class="fas fa-times"></i> Do not collect feedback</span>
    {% endif %}
    <span class="badge bg-primary">Assessors per group = {{ p.number_assessors }}</span>
    <span class="badge bg-primary">Max group size = {{ p.max_group_size }}</span> 
    {% if p.lecture_capture %}
        <span class="badge bg-info text-dark">Requires lecture capture</span>
    {% else %}
        <span class="badge bg-secondary">Lecture capture not required</span>
    {% endif %}
    <p></p>
    <span class="badge bg-info text-dark">Morning: {{ p.morning_session }}</span>
    <span class="badge bg-info text-dark">Afternoon: {{ p.afternoon_session }}</span>
    <span class="badge bg-info text-dark">Format: {{ p.talk_format }}</span>
{% else %}
    <span class="badge bg-secondary">Not required</span>
{% endif %}
"""


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.edit_period_definition', id=period.id) }}">
            <i class="fas fa-cogs fa-fw"></i> Edit period...
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.delete_period_definition', id=period.id) }}">
            <i class="fas fa-trash fa-fw"></i> Delete period
        </a>
    </div>
</div>
"""


# language=jinja2
_name = \
"""
{% if p.name %}
    {{ p.name }}
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
{% if p.start_date %}
    <div>
        <span class="badge bg-info text-dark">Start: {{ p.start_date.strftime("%a %d %b %Y") }}</span>
    </div>
{% endif %}
{% if p.collect_project_feedback %}
    <div>
        <span class="badge bg-info text-dark"><i class="fas fa-check"></i> Collect feedback</span>
    </div>
{% endif %}  
"""


def periods_data(periods: List[SubmissionPeriodDefinition]):

    data = [{'number': p.period,
             'name': render_template_string(_name, p=p),
             'markers': p.number_markers,
             'moderators': p.number_moderators,
             'presentation': render_template_string(_presentation, p=p),
             'menu': render_template_string(_menu, period=p)} for p in periods]

    return jsonify(data)
