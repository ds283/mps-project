#
# Created by David Seery on 2018-10-04.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for


_menu = \
"""
{% if a.availability_closed %}
    <a class="disabled btn btn-sm btn-table-block btn-warning">Force confirm</a>
{% else %}
    <a href="{{ url_for('admin.force_confirm_availability', assessment_id=a.id, faculty_id=f.id) }}" class="btn btn-sm btn-table-block btn-warning">Force confirm</a>
{% endif %}
"""

def outstanding_availability_data(assessors, assessment):

    data = [{'name': {'display': f.faculty.user.name,
                      'sortstring': f.faculty.user.last_name + f.faculty.user.first_name},
             'email': '<a href="mailto:{em}">{em}</a>'.format(em=f.faculty.user.email),
             'menu': render_template_string(_menu, a=assessment, f=f.faculty)} for f in assessors]

    return jsonify(data)
