#
# Created by David Seery on 2018-10-22.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for


_actions = \
"""
{% set available = s.faculty_available(f.id) %}
{% set ifneeded = s.faculty_ifneeded(f.id) %}
<div style="text-align: right;">
    <div class="pull-right">
        {% if available %}
            <a class="btn btn-sm btn-success">
                <i class="fa fa-check"></i> Available
            </a>
            <a class="btn btn-sm btn-default" href="{{ url_for('admin.session_ifneeded', f_id=f.id, s_id=s.id) }}">
                If needed
            </a>
            <a class="btn btn-sm btn-default" href="{{ url_for('admin.session_unavailable', f_id=f.id, s_id=s.id) }}">
                <i class="fa fa-times"></i> Not available
            </a>
        {% elif ifneeded %}
            <a class="btn btn-sm btn-default" href="{{ url_for('admin.session_available', f_id=f.id, s_id=s.id) }}">
                <i class="fa fa-check"></i> Available
            </a>
            <a class="btn btn-sm btn-warning">
                If needed
            </a>
            <a class="btn btn-sm btn-default" href="{{ url_for('admin.session_unavailable', f_id=f.id, s_id=s.id) }}">
                <i class="fa fa-times"></i> Not available
            </a>
        {% else %}
            <a class="btn btn-sm btn-default" href="{{ url_for('admin.session_available', f_id=f.id, s_id=s.id) }}">
                <i class="fa fa-check"></i> Available
            </a>
            <a class="btn btn-sm btn-default" href="{{ url_for('admin.session_ifneeded', f_id=f.id, s_id=s.id) }}">
                If needed
            </a>
            <a class="btn btn-sm btn-danger">
                <i class="fa fa-times"></i> Not available
            </a>
        {% endif %}
    </div>
</div>
"""


_confirmed = \
"""
{% if a.is_faculty_outstanding(f.id) %}
    <span class="label label-warning">No</span>
{% else %}
    <span class="label label-primary">Yes</span>
{% endif %}
"""


def edit_availability_data(assessment, session):
    data = [{'name': {'display': '<a href="mailto:{email}">{name}</a>'.format(email=f.faculty.user.email, name=f.faculty.user.name),
                      'sortstring': f.faculty.user.last_name + f.faculty.user.first_name},
             'confirmed': render_template_string(_confirmed, a=assessment, s=session, f=f.faculty),
             'menu': render_template_string(_actions, s=session, f=f.faculty)} for f in assessment.assessor_list]

    return jsonify(data)
