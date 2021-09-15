#
# Created by David Seery on 10/09/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string

# language=jinja2
_name = \
"""
<a class="text-decoration-none" href="{{ url_for('faculty.live_project', pid=p.id, text='manual reassignment view', url=url_for('convenor.manual_assign', id=r.id)) }}">
    {{ p.name }}
</a>
"""

# language=jinja2
_workload = \
"""
{% set s, m, p = data %}
<div>
    <span class="badge bg-info text-dark">S {{ s }}</span>
    <span class="badge bg-info text-dark">M {{ m }}</span>
    <span class="badge bg-info text-dark">P {{ p }}</span>
    <span class="badge bg-primary">Total {{ s+m+p }}</span>
</div>
"""

# language=jinja2
_action = \
"""
<div class="float-end">
    <a href="{{ url_for('convenor.assign_liveproject', id=rec.id, pid=p.id) }}" class="btn btn-secondary btn-sm">
        Assign
    </a>
</div>
"""


def manual_assign_data(rec, liveprojects):
    data = [{'project': render_template_string(_name, p=p, r=rec),
             'supervisor': '<a class="text-decoration-none" href="mailto:{email}">{name}</a>'.format(email=p.owner.user.email,
                                                                                    name=p.owner.user.name),
             'workload': render_template_string(_workload, data=p.owner.total_CATS_assignment()),
             'menu': render_template_string(_action, rec=rec, p=p)} for p in liveprojects]

    return data
