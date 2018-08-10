#
# Created by David Seery on 10/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify

_affiliations = \
"""
{% for group in f.affiliations %}
    {{ group.make_label()|safe }}
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
"""

_status = \
"""
{% if proj.is_second_marker(f) %}
    <span class="label label-success"><i class="fa fa-check"></i> Enrolled</span>
{% else %}
    <span class="label label-default"><i class-"fa fa-times"></i> Not enrolled</span>
{% endif %}
"""

_enrollments = \
"""
{% for e in f.enrollments %}
    {% if e.marker_state == e.MARKER_ENROLLED %}
        {{ e.pclass.make_label('<i class="fa fa-check"></i> ' + e.pclass.abbreviation)|safe }}
    {% elif e.marker_state == e.MARKER_SABBATICAL %}
        <span class="label label-default"><i class="fa fa-times"></i> {{ e.pclass.abbreviation }} (buyout)</span>
    {% elif e.marker_state == e.MARKER_EXEMPT %}
        <span class="label label-default"><i class="fa fa-times"></i> {{ e.pclass.abbreviation }} (exempt)</span>
    {% else %}
        <span class="label label-danger"><i class="fa fa-exclamation-triangle"></i> {{ e.pclass.abbreviation }} (unknown state)</span>
    {% endif %}
{% else %}
    <span class="label label-default">None</span>
{% endfor %}
"""

_menu = \
"""
<div class="dropdown">
                
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        {% if proj.is_second_marker(f) %}
            <li>
                <a href="{{ url_for('faculty.remove_marker', proj_id=proj.id, mid=f.id) }}">
                    <i class="fa fa-trash"></i> Remove
                </a>
            </li>
        {% elif proj.can_enroll_marker(f) %}
            <li>
                <a href="{{ url_for('faculty.add_marker', proj_id=proj.id, mid=f.id) }}">
                    <i class="fa fa-plus"></i> Enroll
                </a>
            </li>
        {% else %}
            <li class="disabled">
                <a>
                    <i class="fa fa-plus"></i> Enroll
                </a>
            </li>
        {% endif %}
    </ul>
</div>
"""


def build_marker_data(faculty, proj):

    data = [{'name': {
                'display': f.user.name,
                'sortstring': f.user.last_name + f.user.first_name
             },
             'groups': render_template_string(_affiliations, f=f),
             'status': render_template_string(_status, f=f, proj=proj),
             'enrollments': render_template_string(_enrollments, f=f),
             'menu': render_template_string(_menu, f=f, proj=proj)} for f in faculty]

    return jsonify(data)
