#
# Created by David Seery on 05/09/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, render_template_string

from ....database import db
from ....models import MatchingRecord

_student = \
"""
<a href="mailto:{{ sel.student.user.email }}">{{ sel.student.user.name }}</a>
"""


_cohort = \
"""
{{ sel.student.programme.short_label|safe }}
{{ sel.academic_year_label(show_details=True)|safe }}
{{ sel.student.cohort_label|safe }}
"""


_records = \
"""
{% if r.project_id != c.project_id %}
    {% set pclass = r.selector.config.project_class %}
    {% set style = pclass.make_CSS_style()|safe %}
    <span class="badge badge-info" {% if style %}style="{{ style }}"{% endif %}>#{{ r.submission_period }}:
        {{ r.supervisor.user.name }} (No. {{ r.project.number }})</span>
{% else %}
    <span class="badge badge-success">PROJECT MATCH</span>
{% endif %}
{% if r.marker_id != c.marker_id %}
    <span class="badge badge-default">#{{ r.submission_period }}:
        {{ r.marker.user.name }}</span>
{% else %}
    <span class="badge badge-success">MARKER MATCH</span>
{% endif %}
"""


_delta = \
"""
<span class="badge {% if r.hi_ranked %}badge-success{% elif r.lo_ranked %}badge-warning{% else %}badge-info{% endif %}">{{ r.rank }}</span>
<span class="badge badge-primary">&delta; = {{ r.delta }}</span>
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button"
            data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('admin.merge_replace_records', src_id=l.id, dest_id=r.id) }}">
                <i class="fa fa-chevron-circle-right"></i> Replace left to right
            </a>
        </li>
        <li>
            <a href="{{ url_for('admin.merge_replace_records', src_id=r.id, dest_id=l.id) }}">
                <i class="fa fa-chevron-circle-left"></i> Replace right to left
            </a>
        </li>
    </ul>
</div>
"""


def compare_match_data(records):

    data = [{'student': {
                'display': render_template_string(_student, sel=l.selector),
                'sortvalue': l.selector.student.user.last_name + l.selector.student.user.first_name
             },
             'cohort': render_template_string(_cohort, sel=l.selector),
             'record1': render_template_string(_records, r=l, c=r),
             'delta1': {'display': render_template_string(_delta, r=l),
                        'sortvalue': l.delta},
             'record2': render_template_string(_records, r=r, c=l),
             'delta2': {'display': render_template_string(_delta, r=r),
                        'sortvalue': r.delta},
             'menu': render_template_string(_menu, l=l, r=r)} for l, r in records]

    return jsonify(data)
