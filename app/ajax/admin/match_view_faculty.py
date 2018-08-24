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


def _get_attempt_records(q, rec):

    # q is an SQLAlchemy q that produces a list of MatchingRecord instances,
    # typically associated either with faculty assignment as supervisor or marker

    return q.filter_by(matching_id=rec.id).order_by(MatchingRecord.submission_period.asc()).all()


def _compute_CATS(sup, mark, rec):

    # sup, mark are SQL queries that produce a list of MatchingRecord instances

    CATS_supervisor = 0
    CATS_marker = 0

    for item in sup.filter_by(matching_id=rec.id).all():
        config = item.project.config

        if config.CATS_supervision is not None and config.CATS_supervision > 0:
            CATS_supervisor += config.CATS_supervision

    for item in mark.filter_by(matching_id=rec.id).all():
        config = item.project.config

        if config.project_class.uses_marker:
            if config.CATS_marking is not None and config.CATS_marking > 0:
                CATS_marker += config.CATS_marking

    return CATS_supervisor, CATS_marker


def faculty_view_data(faculty, rec):

    data = []

    for f in faculty:

        CATS_supervisor, CATS_marker = _compute_CATS(f.supervisor_matches, f.marker_matches, rec)
        CATS_tot = CATS_supervisor + CATS_marker
        sup_records = _get_attempt_records(f.supervisor_matches, rec)
        mark_records = _get_attempt_records(f.marker_matches, rec)

        gp = {'name': {
                'display': render_template_string(_name, f=f),
                'sortvalue': f.user.last_name + f.user.first_name
             },
             'projects': render_template_string(_projects, recs=sup_records),
             'marking': render_template_string(_marking, recs=mark_records),
             'workload': {
                'display': render_template_string(_workload, sup=CATS_supervisor, mark=CATS_marker,
                                                  tot=CATS_tot),
                'sortvalue': CATS_tot
             } }

        data.append(gp)

    return jsonify(data)
