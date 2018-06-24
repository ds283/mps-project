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
{{ student.user.student_data.programme.label()|safe }}
{{ student.academic_year_label()|safe }}
{{ student.user.student_data.cohort_label()|safe }}
"""


def submitters_data(students, config):

    data = [{'last', student.user.last,
             'first', student.user.first,
             'cohort', render_template_string(_cohort, student=student)} for student in students]

    return jsonify(data)
