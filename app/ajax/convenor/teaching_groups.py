#
# Created by David Seery on 2019-10-04.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify

from ...models import SubmissionPeriodRecord


_group = \
"""
{% for rec in assignments %}
    <div>{{ rec.owner.student.user.name }}</div>
{% endfor %}
"""


def teaching_group_by_faculty(data, config, show_period):
    data = [{'faculty': {'display': f.user.name,
                         'sortvalue': f.user.last_name + f.user.first_name},
             'group': render_template_string(_group,
                                             assignments=f.supervisor_assignments(config.pclass_id,
                                                                                  period=show_period).all())}
            for f in data]

    return jsonify(data)


def _supervisor_data(rec):
    if rec.project is None:
        return {'display': None,
                'sortvalue': None}

    return {'display': rec.project.owner.user.name,
            'sortvalue': rec.project.owner.user.last_name + rec.project.owner.user.first_name}


def teaching_group_by_student(data, config, show_period):
    data = [{'student': {'display': s.student.user.name,
                         'sortvalue': s.student.user.last_name + s.student.user.first_name},
             'supervisor': _supervisor_data(s.get_assignment(show_period))}
            for s in data]

    return jsonify(data)

