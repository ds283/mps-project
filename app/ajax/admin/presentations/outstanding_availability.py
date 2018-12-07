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
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        {% set disabled = a.availability_closed %} 
        <li {% if disabled %}class="disabled"{% endif %}>
            <a {% if not disabled %}href="{{ url_for('admin.force_confirm_availability', assessment_id=a.id, faculty_id=f.id) }}"{% endif %}>
                <i class="fa fa-check"></i> Force confirm
            </a>
        </li>
        <li {% if disabled %}class="disabled"{% endif %}>
            <a {% if not disabled %}href="{{ url_for('admin.remove_assessor', assessment_id=a.id, faculty_id=f.id) }}"{% endif %}>
                <i class="fa fa-trash"></i> Remove
            </a>
        </li>
    </ul>
</div>
"""

def outstanding_availability_data(assessors, assessment):

    data = [{'name': {'display': f.faculty.user.name,
                      'sortstring': f.faculty.user.last_name + f.faculty.user.first_name},
             'email': '<a href="mailto:{em}">{em}</a>'.format(em=f.faculty.user.email),
             'menu': render_template_string(_menu, a=assessment, f=f.faculty)} for f in assessors]

    return jsonify(data)
