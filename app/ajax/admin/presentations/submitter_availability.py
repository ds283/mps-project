#
# Created by David Seery on 2018-10-18.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for


# language=jinja2
_pclass = \
"""
{% set style = pclass.make_CSS_style() %}
<a class="badge badge-info" {% if style %}style="{{ style }}"{% endif %} href="mailto:{{ pclass.convenor_email }}">{{ pclass.abbreviation }} ({{ pclass.convenor_name }})</a>
"""


# language=jinja2
_submitter_actions = \
"""
<div style="text-align: right;">
    <div class="float-right">
        {% if a.not_attending(s.id) %}
            <a {% if editable %}href="{{ url_for('admin.assessment_attending', a_id=a.id, s_id=s.id) }}"{% endif %} class="btn btn-sm btn-secondary btn-table-block {% if not editable %}disabled{% endif %}">
                Attending
            </a>
            <a class="btn btn-sm btn-danger btn-table-block {% if not editable %}disabled{% endif %}">
                Not attending
            </a>
        {% else %}
            <a class="btn btn-sm btn-success btn-table-block {% if not editable %}disabled{% endif %}">
                Attending
            </a>
            <a {% if editable %}href="{{ url_for('admin.assessment_not_attending', a_id=a.id, s_id=s.id) }}"{% endif %} class="btn btn-sm btn-secondary btn-table-block {% if not editable %}disabled{% endif %}">
                Not attending
            </a>
        {% endif %}
        {% set disabled = a.not_attending(s.id) %}
        <a {% if not disabled %}href="{{ url_for('admin.assessment_submitter_availability', a_id=a.id, s_id=s.id, text='submitter management list', url=url_for('admin.assessment_manage_attendees', id=a.id)) }}"{% endif %} class="btn btn-sm btn-info btn-table-block {% if disabled %}disabled{% endif %}">
            Sessions
        </a>
    </div>
</div>
"""


# language=jinja2
_session_actions = \
"""
<div style="text-align: right;">
    <div class="float-right">
        {% if sess.submitter_available(s.id) %}
            <a class="btn btn-success btn-sm {% if not editable %}disabled{% endif %}"><i class="fas fa-check"></i> Available</a>
            <a {% if editable %}href="{{ url_for('admin.submitter_unavailable', sess_id=sess.id, s_id=s.id) }}"{% endif %} class="btn btn-secondary btn-sm {% if not editable %}disabled{% endif %}"><i class="fas fa-times"></i> Not available</a>
        {% else %}
            <a {% if editable %}href="{{ url_for('admin.submitter_available', sess_id=sess.id, s_id=s.id) }}"{% endif %} class="btn btn-secondary btn-sm {% if not editable %}disabled{% endif %}"><i class="fas fa-check"></i> Available</a>
            <a class="btn btn-danger btn-sm {% if not editable %}disabled{% endif %}"><i class="fas fa-times"></i> Not available</a>
        {% endif %}
    </div>
</div>
"""


# language=jinja2
_global_name = \
"""
<a href="mailto:{{ s.submitter.owner.student.user.email }}">{{ s.submitter.owner.student.user.name }}</a>
{% set constraints = s.number_unavailable %}
{% if constraints > 0 %}
    &emsp;
    <span class="badge badge-warning">{{ constraints }} session constraints</span>
{% endif %}
"""


# language=jinja2
_project_name = \
"""
{% if p is none %}
    <span class="badge badge-secondary">No project assigned</span>
{% else %}
    <div>
        <a href="{{ dest_url }}">{{ p.name }}</a>
    </div>
    <div>
        <a class="badge badge-info" href="{{ url_for('convenor.attach_assessors', id=p.parent_id, pclass_id=p.config.pclass_id, url=url, text=text) }}">
            {{ p.number_assessors }} assessors
        </a>
    </div>
{% endif %}
"""


def submitter_session_availability_data(assessment, session, talks, editable=False):
    data = [{'student': {'display': '<a href="mailto:{email}">{name}</a>'.format(email=s.submitter.owner.student.user.email,
                                                                                 name=s.submitter.owner.student.user.name),
                         'sortstring': s.submitter.owner.student.user.last_name + s.submitter.owner.student.user.first_name},
             'pclass': render_template_string(_pclass, pclass=s.submitter.owner.config.project_class),
             'project': render_template_string(_project_name, p=s.submitter.project,
                                               dest_url=url_for('faculty.live_project',
                                                                pid=s.submitter.project.id,
                                                                text='session attendee list',
                                                                url=url_for('admin.submitter_session_availability',
                                                                            id=session.id))
                                               if s.submitter.project is not None else None,
                                               url=url_for('admin.submitter_session_availability', id=session.id),
                                               text='submitter availability for session'),
             'menu': render_template_string(_session_actions, s=s.submitter, a=assessment, sess=session,
                                            editable=editable)} for s in talks]

    return jsonify(data)


def presentation_attendees_data(assessment, talks, editable=False):
    data = [{'student': {'display': render_template_string(_global_name, s=s, a=assessment),
                         'sortstring': s.submitter.owner.student.user.last_name + s.submitter.owner.student.user.first_name},
             'pclass': render_template_string(_pclass, pclass=s.submitter.owner.config.project_class),
             'project': render_template_string(_project_name, p=s.submitter.project,
                                               dest_url=url_for('faculty.live_project',
                                                                pid=s.submitter.project.id,
                                                                text='submitter management list',
                                                                url=url_for('admin.assessment_manage_attendees',
                                                                            id=assessment.id))
                                               if s.submitter.project is not None else None,
                                               url=url_for('admin.assessment_manage_attendees', id=assessment.id),
                                               text='submitter management view'),
             'menu': render_template_string(_submitter_actions, s=s.submitter, a=assessment,
                                            editable=editable)} for s in talks]

    return jsonify(data)
