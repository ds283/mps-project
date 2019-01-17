#
# Created by David Seery on 2019-01-17.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for

from ...shared.utils import get_current_year


_actions = \
"""
<a href="{{ url_for('admin.edit_student', id=s.id, url=url_for('user_approver.correct', url=url, text=text)) }}" class="btn btn-sm btn-default">Edit record...</a>
"""

def correction_data(records, url=None, text=None):
    current_year = get_current_year()

    data = [{'name': {'display': r.user.name,
                      'sortstring': r.user.last_name + r.user.first_name},
             'email': r.user.email,
             'exam_number': r.exam_number,
             'programme': r.programme.full_name,
             'year': r.academic_year_label(current_year),
             'menu': render_template_string(_actions, s=r, url=url, text=text)} for r in records]

    return jsonify(data)
