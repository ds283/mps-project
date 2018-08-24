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
{% if overassigned %}
    <i class="fa fa-exclamation-triangle" style="color:red;"></i>
{% endif %}
"""


_projects = \
"""
{% set ns = namespace(count=0) %}
{% for r in recs %}
    {% if pclass_filter is none or r.selector.config.pclass_id == pclass_filter %}
        {% set ns.count = ns.count + 1 %}
        {% set pclass = r.selector.config.project_class %}
        {% set style = pclass.make_CSS_style() %}
        <span class="label {% if style %}label-default{% else %}label-info{% endif %} btn-table-block" {% if style %}style="{{ style }}"{% endif %}>#{{ r.submission_period }}: {{ r.selector.student.user.name }} (No. {{ r.project.number }})</span>
    {% endif %}
{% endfor %}
{% if ns.count == 0 %}
    <span class="label label-default btn-table-block">None</span>
{% endif %}
{% if overassigned %}
    <div class="has-error">
        <p class="help-block">Supervising workload exceeds CATS limit (assigned={{ assigned }}, max capacity={{ lim }})</p>
    </div>
{% endif %}
"""


_marking = \
"""
{% set ns = namespace(count=0) %}
{% for r in recs %}
    {% if pclass_filter is none or r.selector.config.pclass_id == pclass_filter %}
        {% set ns.count = ns.count + 1 %}
        {% set pclass = r.selector.config.project_class %}
        {% set style = pclass.make_CSS_style() %}
        <span class="label {% if style %}label-default{% else %}label-info{% endif %} btn-table-block" {% if style %}style="{{ style }}"{% endif %}>#{{ r.submission_period }}: {{ r.selector.student.user.name }} (No. {{ r.project.number }})</span>
    {% endif %}
{% endfor %}
{% if ns.count == 0 %}
    <span class="label label-default btn-table-block">None</span>
{% endif %}
{% if overassigned %}
    <div class="has-error">
        <p class="help-block">Marking workload exceeds CATS limit (assigned={{ assigned }}, max capacity={{ lim }})</p>
    </div>
{% endif %}
"""


_workload = \
"""
<span class="label {% if sup_overassigned %}label-danger{% else %}label-info{% endif %}">Supv {{ sup }}</span>
<span class="label {% if mark_overassigned %}label-danger{% else %}label-default{% endif %}">2nd {{ mark }}</span>
<span class="label {% if sup_overassigned or mark_overassigned %}label-danger{% else %}label-primary{% endif %}">Total {{ tot }}</span>
"""


def faculty_view_data(faculty, rec, pclass_filter):

    data = []

    for f in faculty:
        sup_overassigned, CATS_sup, sup_lim = rec.is_supervisor_overassigned(f)
        mark_overassigned, CATS_mark, mark_lim = rec.is_marker_overassigned(f)
        overassigned = sup_overassigned or mark_overassigned

        if pclass_filter is None:
            workload_sup = CATS_sup
            workload_mark = CATS_mark
            workload_tot = CATS_sup + CATS_mark
        else:
            workload_sup, workload_mark = rec.get_faculty_CATS(f, pclass_filter)
            workload_tot = workload_sup + workload_mark

        data.append({'name': {'display': render_template_string(_name, f=f, overassigned=overassigned),
                              'sortvalue': f.user.last_name + f.user.first_name},
                     'projects': render_template_string(_projects, recs=rec.get_supervisor_records(f).all(),
                                                        overassigned=sup_overassigned, assigned=CATS_sup, lim=sup_lim,
                                                        pclass_filter=pclass_filter),
                     'marking': render_template_string(_marking, recs=rec.get_marker_records(f).all(),
                                                       overassigned=mark_overassigned, assigned=CATS_mark, lim=mark_lim,
                                                       pclass_filter=pclass_filter),
                     'workload': {'display': render_template_string(_workload, sup=workload_sup, mark=workload_mark,
                                                                    tot=workload_tot,
                                                                    sup_overassigned=sup_overassigned,
                                                                    mark_overassigned=mark_overassigned),
                                  'sortvalue': CATS_sup + CATS_mark}})

    return jsonify(data)
