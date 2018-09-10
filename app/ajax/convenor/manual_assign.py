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
{% macro faculty_data(fac) %}
    {% set CATS_supv, CATS_mark = fac.CATS_assignment(config.pclass_id) %}
    <div>
        <span class="label label-info">Supv {{ CATS_supv }}</span>
        <span class="label label-info">Mark {{ CATS_mark }}</span>
        <span class="label label-primary">Total {{ CATS_supv+CATS_mark }}</span>
    </div>
{% endmacro %}
{{ faculty_data(owner) }}
"""

_action = \
"""
<div class="pull-right">
    <a href="{{ url_for('convenor.assign_liveproject', id=rec.id, pid=p.id) }}" class="btn btn-default btn-sm">
        Assign
    </a>
</div>
"""

def manual_assign_data(liveprojects, rec):

    data = [{'project': render_template_string(_name, p=p, r=rec),
             'supervisor': {'display': '<a href="mailto:{email}">{name}</a>'.format(email=p.owner.user.email,
                                                                                    name=p.owner.user.name),
                            'sortstring': p.owner.user.last_name + p.owner.user.first_name},
             'workload': {'display': render_template_string(_workload, owner=p.owner, config=p.config),
                          'sortvalue': sum(p.owner.CATS_assignment(p.config.pclass_id))},
             'menu': render_template_string(_action, rec=rec, p=p)} for p in liveprojects]

    return jsonify(data)
