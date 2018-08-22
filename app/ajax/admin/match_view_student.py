#
# Created by David Seery on 22/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, render_template_string


_student = \
"""
<a href="mailto:{{ sel.student.email }}">{{ sel.student.user.name }}</a>
"""


_pclass = \
"""
{% set pclass = sel.config.project_class %}
{% set style = pclass.make_CSS_style() %}
<a class="label {% if style %}label-default{% else %}label-info{% endif %} btn-table-block"
   {% if style %}style="{{ style }}"{% endif %}
   href="mailto:{{ pclass.convenor_email }}">
    {{ pclass.abbreviation }} ({{ pclass.convenor_name }})
</a>
"""


_cohort = \
"""
{{ sel.student.programme.label()|safe }}
{{ sel.academic_year_label()|safe }}
{{ sel.student.cohort_label()|safe }}
"""


_project = \
"""
{% if recs|length == 1 %}
    {% set r = recs[0] %}
    <span class="label label-info">{{ r.project.owner.user.name }} (No. {{ r.project.number }})</span>
{% elif recs|length > 1 %}
    {% for r in recs %}
        <span class="label label-info">{{ r.submission_period }}. {{ r.project.owner.user.name }} (No. {{ r.project.number }})</span>
    {% endfor %}
{% endif %}
"""


_marker = \
"""
{% if recs|length == 1 %}
    {% set r = recs[0] %}
    {% if r.marker %}
        <span class="label label-default">{{ r.marker.user.name }}</span>
    {% else %}
        <span class="label label-default">None</span>
    {% endif %}
{% elif recs|length > 1 %}
    {% for r in recs %}
        {% if r.marker %}
            <span class="label label-default">{{ r.submission_period }}. {{ r.marker.user.name }}</span>
        {% else %}
            <span class="label label-default">None</span>
        {% endif %}
    {% endfor %}
{% endif %}
"""


_rank = \
"""
{% if recs|length == 1 %}
    {% set r = recs[0] %}
    <span class="label label-info">{{ r.rank }}</span>
    <span class="label label-primary">delta = {{ r.rank-1 }}</span>
{% elif recs|length > 1 %}
    {% set ns = namespace(tot=0) %}
    {% for r in recs %}
        {% set ns.tot = ns.tot + r.rank - 1 %}
        <span class="label label-info">{{ r.submission_period }}. {{ r.rank }}</span>
    {% endfor %}
    <span class="label label-primary">delta = {{ ns.tot }}</span>
{% endif %}
"""


def _ranksum(rec_list):

    s = 0

    for rec in rec_list:
        s += rec.rank-1

    return s


def student_view_data(records):

    # records is a list of (lists of) MatchingRecord instances

    data = [{'student': render_template_string(_student, sel=r[0].selector),
             'pclass': render_template_string(_pclass, sel=r[0].selector),
             'cohort': render_template_string(_cohort, sel=r[0].selector),
             'project': render_template_string(_project, recs=r),
             'marker': render_template_string(_marker, recs=r),
             'rank': {
                'display': render_template_string(_rank, recs=r),
                'sortvalue': _ranksum(r)
             } } for r in records]

    return jsonify(data)
