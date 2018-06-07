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
<span class="label label-default">{{ student.user.student_data.programme.name }}</span>
<span class="label label-info">Y{{ student.get_academic_year }}</span>
<span class="label label-success">Cohort {{ student.user.student_data.cohort }}</span>
"""


def submitters_data(students, config):

    data = [{'last', student.user.last,
             'first', student.user.first,
             'cohort', render_template_string(_cohort, student=student)} for student in students]

    return jsonify(data)
