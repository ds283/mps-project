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

from ...models import db, MatchingRecord


_name = \
"""
<a href="mailto:{{ f.user.email }}">{{ f.user.name }}</a>
"""


_projects = \
"""
{% for r in recs %}
    {% set pclass = r.selector.config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    <span class="label {% if style %}label-default{% else %}label-info{% endif %} btn-table-block" {% if style %}style="{{ style }}"{% endif %}>#{{ r.submission_period }}: {{ r.selector.student.user.name }} (No. {{ r.project.number }})</span>
{% else %}
    <span class="label label-default btn-table-block">None</span>
{% endfor %}
"""


_marking = \
"""
{% for r in recs %}
    {% set pclass = r.selector.config.project_class %}
    {% set style = pclass.make_CSS_style() %}
    <span class="label {% if style %}label-default{% else %}label-info{% endif %} btn-table-block" {% if style %}style="{{ style }}"{% endif %}>#{{ r.submission_period }}: {{ r.selector.student.user.name }} (No. {{ r.project.number }})</span>
{% else %}
    <span class="label label-default btn-table-block">None</span>
{% endfor %}
"""


_workload = \
"""
<span class="label label-info">Supv {{ sup }}</span>
<span class="label label-default">2nd {{ mark }}</span>
<span class="label label-primary">Total {{ tot }}</span>
"""


def faculty_view_data(faculty, rec):

    data = []

    for f in faculty:

        CATS_sup, CATS_mark = rec.get_faculty_CATS(f)

        data.append({'name': {'display': render_template_string(_name, f=f),
                              'sortvalue': f.user.last_name + f.user.first_name},
                     'projects': render_template_string(_projects, recs=rec.get_supervisor_records(f).all()),
                     'marking': render_template_string(_marking, recs=rec.get_marker_records(f).all()),
                     'workload': {'display': render_template_string(_workload, sup=CATS_sup, mark=CATS_mark,
                                                                    tot=CATS_sup + CATS_mark),
                                  'sortvalue': CATS_sup + CATS_mark}})

    return jsonify(data)
