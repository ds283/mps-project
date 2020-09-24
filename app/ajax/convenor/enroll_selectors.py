#
# Created by David Seery on 31/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List

from flask import render_template_string, jsonify

from ...models import StudentData
from ...shared.utils import get_current_year


_enroll_action = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle table-button" type="button" data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        <a class="dropdown-item" href="{{ url_for('convenor.enroll_selector', sid=s.id, configid=config.id, convert=1) }}">
            <i class="fas fa-plus fa-fw"></i> Enroll
        </a>
        <a class="dropdown-item" href="{{ url_for('convenor.enroll_selector', sid=s.id, configid=config.id, convert=0) }}">
            <i class="fas fa-plus fa-fw"></i> Enroll without conversion
        </a>
    </div>
</dic>
"""


def enroll_selectors_data(students: List[StudentData], config):
    current_year = get_current_year()

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
                 'display': s.academic_year_label(desired_year=config.year, show_details=True, current_year=current_year),
                 'sortvalue': s.compute_academic_year(desired_year=config.year, current_year=current_year)
             },
             'actions': render_template_string(_enroll_action, s=s, config=config)} for s in students]

    return jsonify(data)
