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
<a href="{{ url_for('convenor.enroll_submitter', sid=s.id, configid=config.id) }}" class="btn btn-warning btn-sm">
    <i class="fas fa-plus"></i> Manually enroll
</a>
"""


def enroll_submitters_data(students: List[StudentData], config):
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
                 'display': s.academic_year_label(desired_year=config.year, show_details=True, current_year=current_yera),
                 'sortvalue': s.compute_academic_year(desired_year=config.year, current_year=current_year)
             },
             'actions': render_template_string(_enroll_action, s=s, config=config)} for s in students]

    return jsonify(data)
