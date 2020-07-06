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
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-right">
        {% set disabled = a.availability_closed %} 
        <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.force_confirm_availability', assessment_id=a.id, faculty_id=assessor.faculty.id) }}"{% endif %}>
            <i class="fa fa-check"></i> Force confirm
        </a>
        <a class="dropdown-item" href="{{ url_for('admin.remove_assessor', assessment_id=a.id, faculty_id=assessor.faculty.id) }}">
            <i class="fa fa-trash"></i> Remove
        </a>
        <a class="dropdown-item {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.availability_reminder_individual', id=assessor.id) }}"{% endif %}>
            <i class="fa fa-envelope-o"></i> Send reminder
        </a>
    </div>
</div>
"""

def outstanding_availability_data(assessors, assessment):

    data = [{'name': {'display': assessor.faculty.user.name,
                      'sortstring': assessor.faculty.user.last_name + assessor.faculty.user.first_name},
             'email': '<a href="mailto:{em}">{em}</a>'.format(em=assessor.faculty.user.email),
             'menu': render_template_string(_menu, a=assessment, assessor=assessor)} for assessor in assessors]

    return jsonify(data)
