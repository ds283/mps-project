#
# Created by David Seery on 2018-10-22.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify

# language=jinja2
_session_actions = """
{% set available = s.faculty_available(f.id) %}
{% set ifneeded = s.faculty_ifneeded(f.id) %}
<div style="text-align: right;">
    <div class="float-end">
        {% if available %}
            <a class="btn btn-sm btn-success {% if not editable %}disabled{% endif %}">
                <i class="fas fa-check fa-fw"></i> Available
            </a>
            <a class="btn btn-sm btn-outline-secondary {% if not editable %}disabled{% endif %}" {% if editable %}href="{{ url_for('admin.assessor_ifneeded', sess_id=s.id, f_id=f.id) }}"{% endif %}>
                If needed
            </a>
            <a class="btn btn-sm btn-outline-secondary {% if not editable %}disabled{% endif %}" {% if editable %}href="{{ url_for('admin.assessor_unavailable', sess_id=s.id, f_id=f.id) }}"{% endif %}>
                <i class="fas fa-times fa-fw"></i> Not available
            </a>
        {% elif ifneeded %}
            <a class="btn btn-sm btn-outline-secondary {% if not editable %}disabled{% endif %}" {% if editable %}href="{{ url_for('admin.assessor_available', sess_id=s.id, f_id=f.id) }}"{% endif %}>
                <i class="fas fa-check fa-fw"></i> Available
            </a>
            <a class="btn btn-sm btn-warning {% if not editable %}disabled{% endif %}">
                If needed
            </a>
            <a class="btn btn-sm btn-outline-secondary {% if not editable %}disabled{% endif %}" {% if editable %}href="{{ url_for('admin.assessor_unavailable', sess_id=s.id, f_id=f.id) }}"{% endif %}>
                <i class="fas fa-times fa-fw"></i> Not available
            </a>
        {% else %}
            <a class="btn btn-sm btn-outline-secondary {% if not editable %}disabled{% endif %}" {% if editable %}href="{{ url_for('admin.assessor_available', sess_id=s.id, f_id=f.id) }}"{% endif %}>
                <i class="fas fa-check fa-fw"></i> Available
            </a>
            <a class="btn btn-sm btn-outline-secondary {% if not editable %}disabled{% endif %}" {% if editable %}href="{{ url_for('admin.assessor_ifneeded', sess_id=s.id, f_id=f.id) }}"{% endif %}>
                If needed
            </a>
            <a class="btn btn-sm btn-danger {% if not editable %}disabled{% endif %}">
                <i class="fas fa-times fa-fw"></i> Not available
            </a>
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_confirmed = """
{% if rec.confirmed %}
    <div class="d-flex flex-column justify-content-start align-items-start gap-1">
        <span class="text-success"><i class="fas fa-check-circle"></i> Confirmed</span>
        {% if rec.confirmed_timestamp is not none %}
            <span class="small text-secondary">Confirmed at {{ rec.confirmed_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}</span>
        {% endif %}
    </div>
{% else %}
    <span class="text-danger"><i class="fas fa-check-circle"></i> Not confirmed</span>
{% endif %}
"""


# language=jinja2
_assessor_actions = """
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.assessment_assessor_availability', a_id=a.id, f_id=f.id, text='assessment assessor list', url=url_for('admin.assessment_manage_assessors', id=a.id)) }}">
            <i class="fas fa-calendar fa-fw"></i> Sessions...
        </a>
        {% set disabled = not editable or not a.is_faculty_outstanding(f.id) %} 
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.force_confirm_availability', assessment_id=a.id, faculty_id=f.id) }}"{% endif %}>
            <i class="fas fa-check fa-fw"></i> {% if not disabled %}Force confirm{% else %}Confirmed{% endif %}
        </a>
        {% set disabled = not editable %}
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.schedule_set_limit', assessment_id=a.id, faculty_id=f.id, text='assessment assessor list', url=url_for('admin.assessment_manage_assessors', id=a.id)) }}"{% endif %}>
            <i class="fas fa-cogs fa-fw"></i> Set assignment limit...
        </a>
        <a class="dropdown-item d-flex gap-2 {% if disabled %}disabled{% endif %}" {% if not disabled %}href="{{ url_for('admin.remove_assessor', assessment_id=a.id, faculty_id=f.id) }}"{% endif %}>
            <i class="fas fa-trash fa-fw"></i> Remove
        </a>
    </div>
</div>
"""


# language=jinja2
_comment = """
{% if rec.comment is not none and rec.comment|length > 0 %}
    <span class="small text-secondary">{{ rec.comment }}</span>
{% else %}
    <span class="badge bg-secondary">None</span>
{% endif %}
"""


# language=jinja2
_availability = """
<span class="badge bg-success">{{ rec.number_available }}</span>
<span class="badge bg-warning text-dark">{{ rec.number_ifneeded }}</span>
<span class="badge bg-danger">{{ rec.number_unavailable }}</span>
"""


# language=jinja2
_name = """
<div class="d-flex flex-column justify-content-start align-items-start gap-2">
    <a class="text-decoration-none" href="mailto:{{ rec.faculty.user.email }}">{{ rec.faculty.user.name }}</a>
    {% if rec.request_email_sent %}
        <span class="small text-secondary"><i class="fas fa-envelope"></i> Invite sent
        {% if rec.request_timestamp is not none %}
            {{ rec.request_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
        {% endif %}
        </span>
    {% endif %}
    {% if rec.reminder_email_sent %}
        <span class="small text-secondary"><i class="fas fa-envelope"></i> Reminder sent
        {% if rec.last_reminder_timestamp is not none %}
            {{ rec.last_reminder_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
        {% endif %}
        </span>
    {% endif %}        
    {% if rec.assigned_limit is not none %}
        <span class="badge bg-primary">Assignment limit {{ rec.assigned_limit }}</span>
    {% endif %}
</div>
"""


def assessor_session_availability_data(assessment, session, assessors, editable=False):
    data = [
        {
            "name": {
                "display": render_template_string(_name, rec=assessor),
                "sortstring": assessor.faculty.user.last_name + assessor.faculty.user.first_name,
            },
            "confirmed": render_template_string(_confirmed, a=assessment, rec=assessor),
            "comment": render_template_string(_comment, rec=assessor),
            "availability": {"display": render_template_string(_availability, rec=assessor), "sortvalue": assessor.number_available},
            "menu": render_template_string(_session_actions, s=session, f=assessor.faculty, editable=editable),
        }
        for assessor in assessors
    ]

    return jsonify(data)


def presentation_assessors_data(assessment, assessors, editable=False):
    data = [
        {
            "name": {
                "display": render_template_string(_name, rec=assessor),
                "sortstring": assessor.faculty.user.last_name + assessor.faculty.user.first_name,
            },
            "confirmed": render_template_string(_confirmed, a=assessment, rec=assessor),
            "comment": render_template_string(_comment, rec=assessor),
            "availability": {"display": render_template_string(_availability, rec=assessor), "sortvalue": assessor.number_available},
            "menu": render_template_string(_assessor_actions, a=assessment, f=assessor.faculty, editable=editable),
        }
        for assessor in assessors
    ]

    return jsonify(data)
