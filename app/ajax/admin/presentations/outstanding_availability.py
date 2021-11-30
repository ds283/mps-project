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


# language=jinja2
_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        {% set disabled = a.availability_closed %} 
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.force_confirm_availability', assessment_id=a.id, faculty_id=assessor.faculty.id) }}"{% endif %}>
            <i class="fas fa-check fa-fw"></i> Force confirm
        </a>
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.remove_assessor', assessment_id=a.id, faculty_id=assessor.faculty.id) }}">
            <i class="fas fa-trash fa-fw"></i> Remove
        </a>
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.availability_reminder_individual', id=assessor.id) }}"{% endif %}>
            <i class="fas fa-envelope fa-fw"></i> Send reminder
        </a>
    </div>
</div>
"""

def outstanding_availability_data(assessors, assessment):

    data = [{'name': {'display': assessor.faculty.user.name,
                      'sortstring': assessor.faculty.user.last_name + assessor.faculty.user.first_name},
             'email': '<a class="text-decoration-none" href="mailto:{em}">{em}</a>'.format(em=assessor.faculty.user.email),
             'menu': render_template_string(_menu, a=assessment, assessor=assessor)} for assessor in assessors]

    return jsonify(data)
