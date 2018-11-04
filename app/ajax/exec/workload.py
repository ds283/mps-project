#
# Created by David Seery on 2018-11-01.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for
from ...shared.sqlalchemy import get_count


_name = \
"""
<a href="mailto:{{ f.user.email }}">{{ f.user.name }}</a>
{% if overassigned %}
    <i class="fa fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
"""


_groups = \
"""
{% for g in f.affiliations %}
    {{ g.make_label()|safe }}
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
"""


_enrollments = \
"""
{% for record in f.ordered_enrollments %}
    <div {% if loop.index > 1 %}style="top-padding: 8px;"{% endif %}>
        {{ record.pclass.make_label()|safe }}
        {% set offered = f.projects_offered(record.pclass) %}
        {% if offered > 0 %}
            <span class="label label-info">Offered={{ offered }}</span>
        {% else %}
            <span class="label label-danger">Offered=0</span>
        {% endif %}

        {% if record.supervisor_state == record.SUPERVISOR_ENROLLED %}
            <span class="label label-success"><i class="fa fa-check"></i> Supv: active</span>
        {% elif record.supervisor_state == record.SUPERVISOR_SABBATICAL %}
            <span class="label label-warning"><i class="fa fa-times"></i> Supv: sabbat</span>
        {% elif record.supervisor_state == record.SUPERVISOR_EXEMPT %}
            <span class="label label-danger"><i class="fa fa-times"></i> Supv: exempt</span>
        {% else %}
            <span class="label label-danger"><i class="fa fa-times"></i> Supv: unknown</span>
        {% endif %}

        {% if record.pclass.uses_marker %}
            {% if record.marker_state == record.MARKER_ENROLLED %}
                <span class="label label-success"><i class="fa fa-check"></i> Mark: active</span>
            {% elif record.marker_state == record.MARKER_SABBATICAL %}
                <span class="label label-warning"><i class="fa fa-times"></i> Mark: sabbat</span>
            {% elif record.marker_state == record.MARKER_EXEMPT %}
                <span class="label label-danger"><i class="fa fa-times"></i> Mark: exempt</span>
            {% else %}
                <span class="label label-danger"><i class="fa fa-times"></i> Mark: unknown</span>
            {% endif %}
        {% endif %}

        {% if record.pclass.uses_presentations %}
            {% if record.presentations_state == record.PRESENTATIONS_ENROLLED %}
                <span class="label label-success"><i class="fa fa-check"></i> Pres: active</span>
            {% elif record.presentations_state == record.PRESENTATIONS_SABBATICAL %}
                <span class="label label-warning"><i class="fa fa-times"></i> Pres: sabbat</span>
            {% elif record.presentations_state == record.PRESENTATIONS_EXEMPT %}
                <span class="label label-danger"><i class="fa fa-times"></i> Pres: exempt</span>
            {% else %}
                <span class="label label-danger"><i class="fa fa-times"></i> Pres: unknown</span>
            {% endif %}
        {% endif %}
    </div>
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
"""


_workload = \
"""
{% for record in f.ordered_enrollments %}
    {{ record.pclass.make_label(record.pclass.abbreviation + ' ' + wkld[record.pclass_id]|string)|safe }}
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
<p></p>
<span class="label label-primary">Total = {{ tot }}</span>
"""


def workload_data(faculty):
    data = []

    for f in faculty:
        workload = {}
        total_workload = 0

        for record in f.enrollments:
            CATS = sum(f.CATS_assignment(record.pclass_id))
            workload[record.pclass_id] = CATS
            total_workload += CATS

        data.append({'name': {'display': render_template_string(_name, f=f),
                              'sortstring': f.user.last_name + f.user.first_name},
                     'groups': render_template_string(_groups, f=f),
                     'enrollments': {'display': render_template_string(_enrollments, f=f),
                                     'sortvalue': get_count(f.enrollments)},
                     'workload': {'display': render_template_string(_workload, f=f, wkld=workload, tot=total_workload),
                                  'sortvalue': total_workload}})

    return jsonify(data)

