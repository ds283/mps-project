#
# Created by David Seery on 29/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from ...shared.utils import get_current_year
from flask import render_template_string, jsonify

from .shared import menu, name


def build_student_data(students):

    year = get_current_year()

    data = [{'name': {
                'display': render_template_string(name, u=u),
                'sortstring': u.last_name + u.first_name},
             'active': u.active_label,
             'programme': s.programme.label,
             'cohort': s.cohort_label,
             'acadyear': {
                 'display': s.academic_year_label(year),
                 'sortvalue': s.academic_year(year)},
             'menu': render_template_string(menu, user=u, pane='students')} for s, u in students]

    return jsonify(data)
