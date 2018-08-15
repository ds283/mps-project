#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_cohort = \
"""
{{ sel.student.programme.label()|safe }}
{{ sel.academic_year_label()|safe }}
{{ sel.student.cohort_label()|safe }}
"""


def submitters_data(students, config):

    data = [{'name': {
                'display': s.student.user.name,
                'sortstring': s.student.user.last_name + s.student.user.first_name
             },
             'cohort': render_template_string(_cohort, sel=s)} for s in students]

    return jsonify(data)
