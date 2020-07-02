#
# Created by David Seery on 10/09/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_name = \
"""
<a href="{{ url_for('faculty.live_project', pid=p.id, text='manual reassignment view', url=url_for('convenor.manual_assign', id=r.id)) }}">
    {{ p.name }}
</a>
"""

_workload = \
"""
{% set s, m, p = data %}
<div>
    <span class="badge badge-info">S {{ s }}</span>
    <span class="badge badge-info">M {{ m }}</span>
    <span class="badge badge-info">P {{ p }}</span>
    <span class="badge badge-primary">Total {{ s+m+p }}</span>
</div>
"""

_action = \
"""
<div class="float-right">
    <a href="{{ url_for('convenor.assign_liveproject', id=rec.id, pid=p.id) }}" class="btn btn-secondary btn-sm">
        Assign
    </a>
</div>
"""

def _compute_total_workload(fac):
    supv = 0
    mark = 0
    pres = 0
    for record in fac.enrollments:
        s, m, p = fac.CATS_assignment(record.pclass)
        supv += s
        mark += m
        pres += p

    return supv, mark, pres, (supv+mark+pres)

def manual_assign_data(liveprojects, rec):
    data = [{'project': render_template_string(_name, p=p, r=rec),
             'supervisor': {'display': '<a href="mailto:{email}">{name}</a>'.format(email=p.owner.user.email,
                                                                                    name=p.owner.user.name),
                            'sortstring': p.owner.user.last_name + p.owner.user.first_name},
             'workload': {'display': render_template_string(_workload, data=p.owner.total_CATS_assignment()),
                          'sortvalue': sum(p.owner.total_CATS_assignment())},
             'menu': render_template_string(_action, rec=rec, p=p)} for p in liveprojects]

    return jsonify(data)
