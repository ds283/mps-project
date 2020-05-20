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
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle table-button" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('convenor.enroll_selector', sid=s.id, configid=config.id, convert=1) }}">
                <i class="fa fa-plus"></i> Enroll
            </a>
        <li>
        <li>
            <a href="{{ url_for('convenor.enroll_selector', sid=s.id, configid=config.id, convert=0) }}">
                <i class="fa fa-plus"></i> Enroll without conversion
            </a>
        <li>
    </ul>
</dic>
"""


def enroll_selectors_data(students, config):
    data = [{'name': {
                'display': s.user.name,
                'sortstring': s.user.last_name + s.user.first_name
             },
             'programme': s.programme.label,
             'cohort': {
                 'display': s.cohort_label,
                 'sortvalue': s.cohort
             },
             'acadyear': {
                 'display': s.academic_year_label(config.year, show_details=True),
                 'sortvalue': s.academic_year(config.year)
             },
             'actions': render_template_string(_enroll_action, s=s, config=config)} for s in students]

    return jsonify(data)
