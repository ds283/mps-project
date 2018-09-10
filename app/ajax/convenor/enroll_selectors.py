#
# Created by David Seery on 31/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import render_template_string, jsonify


_enroll_action = \
"""
<a href="{{ url_for('convenor.enroll_selector', sid=s.id, configid=config.id) }}" class="btn btn-warning btn-sm">
    <i class="fa fa-plus"></i> Manually enroll
</a>
"""


def enroll_selectors_data(students, config):

    data = [{'name': {
                'display': s.user.name,
                'sortstring': s.user.last_name + s.user.first_name
             },
             'programme': s.programme.label,
             'cohort': s.cohort_label,
             'acadyear': {
                 'display': s.academic_year_label(config.year),
                 'sortvalue': s.academic_year(config.year)},
             'actions': render_template_string(_enroll_action, s=s, config=config)} for s in students]

    return jsonify(data)
